import json
import math
import sys


def load_funcs(path):
    """Load function signatures from JSON file."""
    data = json.load(open(path))
    return {f["fqname"]: f for f in data}


def load_calls(path):
    """Load call sites from JSON file."""
    return json.load(open(path))


def required_positional(func):
    """Count required positional arguments."""
    return sum(1 for a in func["positional"] if not a["has_default"])


def total_positional(func):
    """Count total positional arguments."""
    return len(func["positional"])


def get_severity(change_type):
    """Get severity score for a change type."""
    scores = {
        "REMOVED": 1.0,
        "REQUIRED": 0.9,
        "POSITIONAL REORDER": 0.8,
        "KWONLY REMOVED": 0.8,
        "*args REMOVED": 0.7,
        "**kwargs REMOVED": 0.7,
        "OPTIONAL": 0.3,
        "ADDED": 0.1,
    }
    for key, score in scores.items():
        if key in change_type:
            return score
    return 0.5


def exposure(count, max_count):
    """Calculate exposure score from call count."""
    if count == 0:
        return 0
    return min(1.0, math.log(1 + count) / math.log(1 + max_count))


def analyze(sigs_path, calls_path, runtime_path=None):
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
    runtime = {}
    if runtime_path:
        try:
            rt_data = json.load(open(runtime_path))
            runtime = {item["function"]: item.get("count", 1) for item in rt_data}
        except Exception:
            pass

    # Get max count for exposure calculation
    max_count = max(runtime.values()) if runtime else 1

    issues = []

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


def main():
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


if __name__ == "__main__":
    main()

    funcs = load_funcs(sys.argv[1])
    calls = load_calls(sys.argv[2])

    # Load runtime data if provided
    runtime = {}
    if len(sys.argv) > 3:
        try:
            rt_data = json.load(open(sys.argv[3]))
            runtime = {item["function"]: item.get("count", 1) for item in rt_data}
        except Exception:
            pass

    # Get max count for exposure calculation
    max_count = max(runtime.values()) if runtime else 1

    issues = []

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

    # Output summary
    for level in ["HIGH", "MEDIUM", "LOW"]:
        level_issues = [i for i in issues if i["risk"] == level]
        if level_issues:
            print(f"[{level}] {len(level_issues)} issues:")
            for i in level_issues[:5]:
                print(f"  {i['function']} -> {i['change']} (count: {i['count']})")

    if any(i["risk"] == "HIGH" for i in issues):
        sys.exit(1)
