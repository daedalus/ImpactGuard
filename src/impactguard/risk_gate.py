import json
import math
import sys

# Severity scores for different types of changes
SEVERITY_SCORES = {
    "REMOVED": 1.0,
    "REQUIRED": 0.9,
    "POSITIONAL REORDER": 0.8,
    "KWONLY REMOVED": 0.8,
    "*args REMOVED": 0.7,
    "**kwargs REMOVED": 0.7,
    "OPTIONAL": 0.3,
    "ADDED": 0.1,
}


def get_severity(change_type):
    """Get severity score for a change type."""
    for key, score in SEVERITY_SCORES.items():
        if key in change_type:
            return score
    return 0.5


def exposure(count, max_count):
    """Calculate exposure score from call count."""
    if count == 0:
        return 0
    return min(1.0, math.log(1 + count) / math.log(1 + max_count))


def confidence(samples, threshold=100):
    """Calculate confidence from sample count."""
    return min(1.0, samples / threshold)


def classify(severity, count, max_count, samples):
    """Classify risk level based on severity, exposure, and confidence."""
    E = exposure(count, max_count)
    C = confidence(samples)

    if C < 0.3:
        return "UNKNOWN", E, C

    if severity > 0.8 and E > 0.1:
        return "HIGH", E, C

    if severity > 0.5 and E > 0.01:
        return "MEDIUM", E, C

    return "LOW", E, C


def run(diff_path, runtime_path, output_path=None):
    """Run risk analysis pipeline.

    Args:
        diff_path: Path to diff text file.
        runtime_path: Path to runtime data JSON.
        output_path: Optional output path for report JSON.

    Returns:
        List of risk report items.
    """
    # Parse diff file
    try:
        diff_text = open(diff_path).read()
    except Exception:
        diff_text = ""

    # Load runtime data
    try:
        runtime_data = json.load(open(runtime_path))
        runtime = {item["function"]: item.get("count", 1) for item in runtime_data}
    except Exception:
        runtime = {}

    max_count = max(runtime.values()) if runtime else 1

    # Parse breaking/non-breaking from diff
    report = []

    for line in diff_text.splitlines():
        if (
            line.startswith("REMOVED:")
            or "REQUIRED" in line
            or "POSITIONAL" in line
            or "KWONLY" in line
        ):
            parts = line.split(": ", 1)
            func_name = parts[-1] if len(parts) > 1 else line.split(":")[-1]
            current_change = line.split(":")[0].strip()

            count = runtime.get(func_name.strip(), 0)
            severity = get_severity(line)
            risk, E, C = classify(severity, count, max_count, count)

            report.append(
                {
                    "function": func_name.strip(),
                    "risk": risk,
                    "change": current_change,
                    "exposure": E,
                    "confidence": C,
                    "details": f"called {count} times" if count > 0 else "not observed",
                }
            )

    # Sort by risk level
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}
    report.sort(key=lambda x: risk_order.get(x["risk"], 4))

    if output_path:
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

    return report


def main(diff_path=None, runtime_path=None, output_path=None):
    """CLI entry point."""
    if diff_path is None:
        if len(sys.argv) < 3:
            print("Usage: python risk_gate.py <diff.txt> <runtime.json> [output.json]")
            sys.exit(1)
        diff_path = sys.argv[1]
        runtime_path = sys.argv[2]
        output_path = sys.argv[3] if len(sys.argv) > 3 else "report.json"

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


if __name__ == "__main__":
    main()
