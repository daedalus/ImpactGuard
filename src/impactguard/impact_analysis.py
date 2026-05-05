import json
import math
import sys
from typing import Any

from .risk_model import get_severity, exposure


def required_positional(func: dict[str, Any]) -> int:
    """Count required positional arguments."""
    return sum(1 for a in func.get("positional", []) if not a.get("has_default"))

def total_positional(func: dict[str, Any]) -> int:
    """Count total positional arguments."""
    return len(func.get("positional", []))

def load_funcs(path: str) -> dict[str, dict[str, Any]]:
    """Load function signatures from JSON file."""
    data: list[dict[str, Any]] = json.load(open(path))
    return {f["fqname"]: f for f in data}

def load_calls(path: str) -> list[dict[str, Any]]:
    """Load call sites from JSON file."""
    data: list[dict[str, Any]] = json.load(open(path))
    return data

def analyze(
    sigs_path: str, calls_path: str, runtime_path: str | None = None
) -> list[dict[str, Any]]:
    """Analyze impact of signature changes on call sites.

    Args:
        sigs_path: Path to signatures JSON file.
        calls_path: Path to calls JSON file.
        runtime_path: Optional path to runtime data JSON.

    Returns:
        List of impact issues.
    """
    funcs = load_funcs(sigs_path)
    calls = load_calls(calls_path)

    # Load runtime data if provided
    runtime: dict[str, int] = {}
    if runtime_path:
        try:
            rt_data = json.load(open(runtime_path))
            runtime = {item["function"]: item.get("count", 1) for item in rt_data}
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Failed to parse runtime data: {e}", file=sys.stderr)
            runtime = {}

    # Get max count for exposure calculation
    max_count = max(runtime.values()) if runtime else 1

    issues: list[dict[str, Any]] = []

    for call in calls:
        target = call.get("fqname", call.get("name", ""))

        if target not in funcs:
            # Try fallback matching
            matches = [f for f in funcs if f.endswith("." + target.split(".")[-1])]
            if len(matches) == 1:
                target = matches[0]
            else:
                continue

        f = funcs[target]

        if call.get("has_starargs") or call.get("has_kwargs"):
            continue

        min_args = required_positional(f)
        max_args = total_positional(f) if not f["vararg"] else float("inf")

        argc = call.get("args", 0)

        if argc < min_args or argc > max_args:
            func_name = f.get("name", target)
            count = runtime.get(f"{func_name}", 1)
            exp = exposure(count, max_count)

            severity = 0.9 if argc < min_args else 0.3
            risk_level = (
                "HIGH"
                if severity > 0.8 and exp > 0.1
                else "MEDIUM"
                if severity > 0.5
                else "LOW"
            )

            issues.append(
                {
                    "function": target,
                    "risk": risk_level,
                    "change": "missing args" if argc < min_args else "too many args",
                    "exposure": exp,
                    "confidence": min(1.0, count / 100),
                    "file": call.get("file", ""),
                    "lineno": call.get("lineno", 0),
                    "count": count,
                }
            )

    return issues


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 3:
        print(
            "Usage: python impact_analysis.py <signatures.json> <calls.json> [runtime.json]"
        )
        sys.exit(1)

    issues = analyze(
        sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None
    )

    # Output summary
    for level in ["HIGH", "MEDIUM", "LOW"]:
        level_issues = [i for i in issues if i["risk"] == level]
        if level_issues:
            print(f"[{level}] {len(level_issues)} issues:")
            for i in level_issues[:5]:
                print(f"  {i['function']} -> {i['change']} (count: {i['count']})")

    if any(i["risk"] == "HIGH" for i in issues):
        sys.exit(1)

