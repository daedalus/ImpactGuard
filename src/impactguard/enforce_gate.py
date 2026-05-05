import json
import sys
from typing import Any


def enforce(
    diff_path: str, runtime_path: str, output_path: str | None = None
) -> int:
    """Enforce gate - block on HIGH risk.

    Args:
        diff_path: Path to diff text file.
        runtime_path: Path to runtime data JSON.
        output_path: Optional output path for report JSON.

    Returns:
        1 if HIGH risk detected, 0 otherwise.
    """
    from .risk_gate import run

    report: list[dict[str, Any]] = run(diff_path, runtime_path, output_path)

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


def enforce_report(report_path: str) -> int:
    """Backward-compatible: enforce from pre-generated report JSON."""
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
        elif risk == "UNKNOWN":
            has_unknown = True

    if has_high:
        print("❌ Blocking: HIGH risk API changes detected")
        return 1

    if has_unknown:
        print("⚠️ Warning: Unknown risk areas detected")

    print("✅ API risk acceptable")
    return 0
