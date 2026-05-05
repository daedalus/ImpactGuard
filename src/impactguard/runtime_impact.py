"""Runtime impact analysis - correlates signatures with runtime call data."""
from __future__ import annotations

import json
import sys
from typing import Any


def load_funcs(path: str) -> dict[str, dict[str, Any]]:
    """Load function signatures from JSON file."""
    data: list[dict[str, Any]] = json.load(open(path))
    return {f["fqname"]: f for f in data}


def required_positional(func: dict[str, Any]) -> int:
    """Count required positional arguments."""
    return sum(1 for a in func.get("positional", []) if not a.get("has_default"))


def total_positional(func: dict[str, Any]) -> int:
    """Count total positional arguments."""
    return len(func.get("positional", []))


def analyze(signatures_path: str, calls_path: str) -> list[dict[str, Any]]:
    """Analyze runtime impact of signature changes.

    Args:
        signatures_path: Path to signatures JSON file.
        calls_path: Path to runtime calls JSON (dict of {func_name: count}).

    Returns:
        List of impact issue dictionaries with keys: function, risk, count.
    """
    funcs = load_funcs(signatures_path)
    try:
        runtime: dict[str, int] = json.load(open(calls_path))
    except Exception:
        runtime = {}

    issues: list[dict[str, Any]] = []

    for fqname, func in funcs.items():
        name = func.get("name", fqname.split(":")[-1])
        count = runtime.get(name, runtime.get(fqname, 0))
        min_args = required_positional(func)

        if min_args > 0 and count == 0:
            issues.append(
                {
                    "function": fqname,
                    "risk": "UNKNOWN",
                    "change": "not observed at runtime",
                    "count": 0,
                }
            )
        elif count > 0:
            issues.append(
                {
                    "function": fqname,
                    "risk": "LOW",
                    "change": "observed",
                    "count": count,
                }
            )

    return issues


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python runtime_impact.py <signatures.json> <calls.json>")
        sys.exit(1)
    result = analyze(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
