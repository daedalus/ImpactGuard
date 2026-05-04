import json
import sys
from typing import Any


def load_funcs(path: str) -> dict[str, dict[str, Any]]:
    data = json.load(open(path))
    return {f["fqname"]: f for f in data}


def required_positional(f: dict[str, Any]) -> int:
    return sum(1 for a in f["positional"] if not a["has_default"])


def total_positional(f: dict[str, Any]) -> int:
    return len(f["positional"])


if __name__ == "__main__":
    funcs = load_funcs(sys.argv[1])
    calls = json.load(open(sys.argv[2]))

    issues = []

    for c in calls:
        name = c["function"]

        if name not in funcs:
            continue

        f = funcs[name]

        argc = c["args_count"]
        min_args = required_positional(f)
        max_args = total_positional(f) if not f["vararg"] else float("inf")

        if argc < min_args:
            issues.append(f"{name} → missing args at runtime ({argc} < {min_args})")

        elif argc > max_args:
            issues.append(f"{name} → too many args at runtime ({argc} > {max_args})")

    print("=== RUNTIME BREAKAGES ===")
    print("\n".join(issues) or "None")

    if issues:
        sys.exit(1)
