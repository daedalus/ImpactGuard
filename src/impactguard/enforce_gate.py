import json
import sys


def enforce(diff_path: str, runtime_path: str, output_path: str | None = None) -> int:
    """Enforce gate - run risk analysis and block on HIGH risk.

    Args:
        diff_path: Path to diff text file.
        runtime_path: Path to runtime data JSON file.
        output_path: Optional path to write report JSON.

    Returns:
        1 if HIGH risk detected (blocks build), 0 otherwise.
    """
    from .risk_gate import run

    report = run(diff_path, runtime_path, output_path)
    return _evaluate_report(report)


def enforce_report(report_path: str) -> int:
    """Enforce gate from a pre-generated report JSON (backward-compatible).

    Args:
        report_path: Path to pre-generated risk report JSON file.

    Returns:
        1 if HIGH risk detected (blocks build), 0 otherwise.
    """
    try:
        report = json.load(open(report_path))
    except Exception:
        print("⚠️ Could not read report")
        return 0
    return _evaluate_report(report)


def _evaluate_report(report: list) -> int:
    """Evaluate a risk report and print status messages.

    Args:
        report: List of risk report items.

    Returns:
        1 if HIGH risk detected, 0 otherwise.
    """
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
        return 1

    if has_unknown:
        print("⚠️ Warning: Unknown risk areas detected")

    print("✅ API risk acceptable")
    return 0
