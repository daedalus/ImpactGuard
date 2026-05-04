import json
import sys


def enforce(report_path: str) -> int:
    try:
        report = json.load(open(report_path))
    except Exception:
        print("⚠️ Could not read report")
        return 0

    has_high = False
    has_unknown = False

    for item in report:
        risk = item.get("risk", "LOW")
        func = item.get("function", "unknown")

        if risk == "HIGH":
            has_high = True
            print(f"🔴 HIGH — {func}")
            print(f"   change: {item.get('change', '')}")
            print(f"   exposure: {item.get('exposure', 0):.2%}")
            print(f"   confidence: {item.get('confidence', 0):.2f}")
            print()
        elif risk == "UNKNOWN":
            has_unknown = True

    if has_high:
        print("❌ Blocking: HIGH risk API changes detected")
        return 1

    if has_unknown:
        print("⚠️ Warning: Unknown risk areas detected")

    print("✅ API risk acceptable")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python enforce_gate.py <report.json>")
        sys.exit(1)

    sys.exit(enforce(sys.argv[1]))
