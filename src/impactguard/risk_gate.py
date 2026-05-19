import json
import sys
from typing import Any

from ._logging import get_logger
from .risk_model import _effective_severity_scores, classify, get_severity
from .runtime_intelligence import (
    build_runtime_index,
    load_runtime_observations,
    lookup_runtime_count,
)

_log = get_logger(__name__)
_UNKNOWN_SEVERITY = 0.5


def _get_first(item: dict[str, Any], keys: tuple[str, ...], default: str = "") -> str:
    """Return first non-empty string value from a dict for candidate keys."""
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _parse_change_line(line: str) -> dict[str, str] | None:
    """Parse a textual change line into a structured change record."""
    text = line.strip()
    if not text:
        return None
    parts = text.split(":", 1)
    if len(parts) < 2:
        return None
    change_type = parts[0].strip()
    remainder = parts[1].strip()
    fqname = remainder.split(" ")[0].strip()
    if not change_type or not fqname:
        return None
    return {"change": change_type, "function": fqname}


def parse_change_line(line: str) -> dict[str, str] | None:
    """Public helper for parsing textual change lines to structured records."""
    return _parse_change_line(line)


def _normalize_changes(
    changes: list[str] | list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Normalize mixed textual/structured changes to structured records."""
    normalized: list[dict[str, str]] = []
    for item in changes:
        if isinstance(item, str):
            parsed = parse_change_line(item)
            if parsed is not None:
                normalized.append(parsed)
            continue
        if not isinstance(item, dict):
            continue
        change_type = _get_first(item, ("change", "change_type", "type"))
        function = _get_first(item, ("function", "fqname", "symbol"))
        if change_type and function:
            normalized.append({"change": change_type, "function": function})
    return normalized


_SKIP_PREFIXES = ("OPTIONAL", "ADDED", "TYPE_WIDENED", "RETURN_TYPE_WIDENED")


def _should_skip_change(change_type: str, fqname: str, seen: set[str]) -> bool:
    if not change_type or not fqname:
        return True
    if fqname in seen:
        return True
    for p in _SKIP_PREFIXES:
        if change_type.startswith(p):
            return True
    return False


def _build_risk_report(
    normalized_changes: list[dict[str, Any]],
    runtime: dict[str, int],
    max_count: int,
    lambda_: float,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    known_prefixes = tuple(_effective_severity_scores().keys())
    report: list[dict[str, Any]] = []

    for change in normalized_changes:
        change_type = str(change["change"]).strip()
        fqname = str(change["function"]).strip()

        if _should_skip_change(change_type, fqname, seen):
            continue
        seen.add(fqname)

        severity = get_severity(change_type)
        if severity == _UNKNOWN_SEVERITY and not any(
            change_type.startswith(k) for k in known_prefixes
        ):
            continue

        count = lookup_runtime_count(runtime, fqname)
        risk, exp, conf = classify(
            severity, count, max_count, count, lambda_, change_type
        )

        report.append(
            {
                "function": fqname,
                "risk": risk,
                "change": change_type,
                "exposure": exp,
                "confidence": conf,
                "details": f"called {count} times" if count > 0 else "not observed",
            }
        )

    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}
    report.sort(key=lambda x: risk_order.get(str(x["risk"]), 4))
    return report


def _load_runtime_data(runtime_path: str) -> tuple[dict[str, int], int]:
    try:
        runtime = build_runtime_index(load_runtime_observations(runtime_path))
    except (json.JSONDecodeError, KeyError, OSError):
        runtime = {}
    max_count = max(runtime.values()) if runtime else 1
    return runtime, max_count


def run_from_changes(
    changes: list[str] | list[dict[str, Any]],
    runtime_path: str,
    output_path: str | None = None,
    lambda_: float = 1.0,
) -> list[dict[str, Any]]:
    """Run risk analysis pipeline from structured change entries."""
    normalized_changes = _normalize_changes(changes)
    _log.debug(
        "Running risk analysis on %d structured change(s)", len(normalized_changes)
    )

    runtime, max_count = _load_runtime_data(runtime_path)
    report = _build_risk_report(normalized_changes, runtime, max_count, lambda_)

    high_count = sum(1 for r in report if r["risk"] == "HIGH")
    _log.debug(
        "Risk analysis complete: %d item(s) assessed, %d HIGH", len(report), high_count
    )
    if high_count:
        _log.warning("%d HIGH-risk API change(s) detected", high_count)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        _log.debug("Risk report written to '%s'", output_path)

    return report


def run(
    diff_path: str,
    runtime_path: str,
    output_path: str | None = None,
    lambda_: float = 1.0,
    changes: list[str] | list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run risk analysis pipeline.

    Args:
        diff_path: Path to diff text file.
        runtime_path: Path to runtime data JSON.
        output_path: Optional output path for report JSON.
        lambda_: Sensitivity multiplier (default 1.0). Values >1 increase
            sensitivity (more changes flagged HIGH/MEDIUM); values <1 decrease it.

    Returns:
        List of risk report items.
    """
    # Parse diff file
    try:
        with open(diff_path) as f:
            diff_text = f.read()
    except OSError as exc:
        raise OSError(f"Cannot read diff file '{diff_path}': {exc}") from exc

    _log.debug("Running risk analysis on diff '%s'", diff_path)

    effective_changes: list[str] | list[dict[str, Any]]
    if changes is not None:
        effective_changes = changes
    else:
        effective_changes = diff_text.splitlines()
    return run_from_changes(effective_changes, runtime_path, output_path, lambda_)


def risk_main_cli(
    diff_path: str | None = None,
    runtime_path: str | None = None,
    output_path: str | None = None,
) -> list[dict[str, Any]]:
    """CLI entry point."""
    if diff_path is None:
        if len(sys.argv) < 3:
            print("Usage: python risk_gate.py <diff.txt> <runtime.json> [output.json]")
            sys.exit(1)
        diff_path = sys.argv[1]
        runtime_path = sys.argv[2]
        output_path = sys.argv[3] if len(sys.argv) > 3 else "report.json"

    if runtime_path is None:
        return []

    report = run(diff_path, runtime_path, output_path)

    # Print summary
    for level in ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
        level_items = [i for i in report if i["risk"] == level]
        if level_items:
            print(f"\n[{level}] {len(level_items)} issues:")
            for item in level_items[:5]:
                print(f"  {item['function']} - {item['change']}")

    print(f"\nReport written to {output_path}")
    return report


#: Public alias for the CLI entry point (backward-compat and test access).
main = risk_main_cli
