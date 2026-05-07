import json
import sys
from typing import Any

from .risk_model import classify, get_severity, _effective_severity_scores


def run(
    diff_path: str,
    runtime_path: str,
    output_path: str | None = None,
    lambda_: float = 1.0,
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

    # Load runtime data
    try:
        with open(runtime_path) as f:
            runtime_data = json.load(f)
        runtime = {item["function"]: item.get("count", 1) for item in runtime_data}
    except Exception:
        runtime = {}

    max_count = max(runtime.values()) if runtime else 1

    # Parse breaking/non-breaking from diff
    report: list[dict[str, Any]] = []
    seen_functions: set[str] = set()

    for line in diff_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Extract change type (before first colon)
        parts = line.split(":", 1)
        if len(parts) < 2:
            continue
        change_type = parts[0].strip()
        func_name = parts[1].strip()
        
        # Isolate the fqname (before first space) - change entries like
        # "TYPE_CHANGED: mod.py:foo arg 'x' int -> str" have extra text
        fqname = func_name.split(' ')[0].strip()

        # Skip if we've already processed this function
        if fqname in seen_functions:
            continue
        seen_functions.add(fqname)

        # Skip non-breaking entries (these are informational only)
        if change_type.startswith("OPTIONAL") or change_type.startswith("ADDED") or change_type.startswith("TYPE_WIDENED") or change_type.startswith("RETURN_TYPE_WIDENED"):
            continue

        # Get severity - validates that this is a known change type
        severity = get_severity(line)
        # Skip if not a recognized change type (unknown types return 0.5 default)
        if severity == 0.5 and not any(
            change_type.startswith(k) for k in _effective_severity_scores().keys()
        ):
            # Not a recognized change type, skip
            continue

        count = runtime.get(fqname, 0)
        if count == 0:
            # Try normalizing "module.py:func_name" → "module.func_name"
            normalized = fqname.strip()
            if ".py:" in normalized:
                normalized = normalized.replace(".py:", ".")
                count = runtime.get(normalized, 0)
        current_change = change_type
        risk, exp, conf = classify(
            severity, count, max_count, count, lambda_, current_change
        )

        report.append(
            {
                "function": fqname,
                "risk": risk,
                "change": current_change,
                "exposure": exp,
                "confidence": conf,
                "details": f"called {count} times" if count > 0 else "not observed",
            }
        )

    # Sort by risk level
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}
    report.sort(key=lambda x: risk_order.get(str(x["risk"]), 4))

    if output_path:
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

    return report


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
