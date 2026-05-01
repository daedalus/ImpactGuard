import json
import sys
import math

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
    for key, score in SEVERITY_SCORES.items():
        if key in change_type:
            return score
    return 0.5


def exposure(count, max_count):
    if count == 0:
        return 0
    return min(1.0, math.log(1 + count) / math.log(1 + max_count))


def confidence(samples, threshold=100):
    return min(1.0, samples / threshold)


def classify(severity, count, max_count, samples):
    E = exposure(count, max_count)
    C = confidence(samples)

    if C < 0.3:
        return "UNKNOWN", E, C

    if severity > 0.8 and E > 0.1:
        return "HIGH", E, C

    if severity > 0.5 and E > 0.01:
        return "MEDIUM", E, C

    return "LOW", E, C


def main():
    if len(sys.argv) < 3:
        print("Usage: python risk_gate.py <diff.txt> <runtime.json> [output.json]")
        sys.exit(1)

    diff_file = sys.argv[1]
    runtime_file = sys.argv[2]
    output = sys.argv[3] if len(sys.argv) > 3 else "report.json"

    # Parse diff file
    try:
        diff_text = open(diff_file).read()
    except Exception:
        diff_text = ""

    # Load runtime data
    try:
        runtime_data = json.load(open(runtime_file))
        runtime = {item["function"]: item.get("count", 1) for item in runtime_data}
    except Exception:
        runtime = {}

    max_count = max(runtime.values()) if runtime else 1

    # Parse breaking/non-breaking from diff
    report = []
    current_func = None
    current_change = ""

    for line in diff_text.splitlines():
        if line.startswith("REMOVED:") or "REQUIRED" in line or "POSITIONAL" in line or "KWONLY" in line:
            func_name = line.split(": ", 1)[-1] if ": " in line else line.split(":")[-1]
            current_func = func_name.strip()
            current_change = line.split(":")[0].strip()

            count = runtime.get(func_name, 0)
            severity = get_severity(line)
            risk, E, C = classify(severity, count, max_count, count)

            report.append({
                "function": func_name,
                "risk": risk,
                "change": current_change,
                "exposure": E,
                "confidence": C,
                "details": f"called {count} times" if count > 0 else "not observed"
            })

    # Sort by risk level
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}
    report.sort(key=lambda x: risk_order.get(x["risk"], 4))

    with open(output, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    for level in ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
        level_items = [i for i in report if i["risk"] == level]
        if level_items:
            print(f"\n[{level}] {len(level_items)} issues:")
            for item in level_items[:5]:
                print(f"  {item['function']} - {item['change']}")

    print(f"\nReport written to {output}")
    return report


if __name__ == "__main__":
    main()
