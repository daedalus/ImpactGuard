import json
import sys
from typing import Any


def enforce(
    diff_path: str,
    runtime_path: str,
    output_path: str | None = None,
    block_unknown: bool | None = None,
    lambda_: float = 1.0,
) -> int:
    """Enforce gate - block on HIGH risk.

    Args:
        diff_path: Path to diff text file.
        runtime_path: Path to runtime data JSON.
        output_path: Optional output path for report JSON.
        block_unknown: When *True*, treat UNKNOWN risk as blocking just like
            HIGH.  When *None* (default) the value is read from the config
            file (``[impactguard.risk] block_unknown``).
        lambda_: Sensitivity multiplier (default 1.0). Values >1 increase
            sensitivity (more changes flagged HIGH); values <1 decrease it.

    Returns:
        1 if HIGH risk detected (or UNKNOWN when blocking), 0 otherwise.
    """
    from .config import get as cfg_get
    from .risk_gate import run

    if block_unknown is None:
        block_unknown = bool(cfg_get("risk", "block_unknown", False))

    report: list[dict[str, Any]] = run(
        diff_path, runtime_path, output_path, lambda_=lambda_
    )

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
            if block_unknown:
                print(f"🟡 UNKNOWN — {func}")
                print(f"   change: {item.get('change', '')}")
                print()

    if has_high:
        print("❌ Blocking: HIGH risk API changes detected")
        return 1

    if has_unknown and block_unknown:
        print("❌ Blocking: UNKNOWN risk API changes detected (block_unknown=true)")
        return 1

    if has_unknown:
        print("⚠️ Warning: Unknown risk areas detected")

    print("✅ API risk acceptable")
    return 0


def enforce_report(report_path: str, block_unknown: bool | None = None) -> int:
    """Backward-compatible: enforce from pre-generated report JSON.

    Args:
        report_path: Path to the risk report JSON.
        block_unknown: When *True*, UNKNOWN risk is treated as blocking.
            Defaults to the config value.
    """
    from .config import get as cfg_get

    if block_unknown is None:
        block_unknown = bool(cfg_get("risk", "block_unknown", False))

    try:
        with open(report_path) as f:
            report = json.load(f)
    except OSError as exc:
        print(f"⚠️ Could not read report: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"⚠️ Could not parse report (invalid JSON): {exc}", file=sys.stderr)
        return 2

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
            if block_unknown:
                print(f"🟡 UNKNOWN — {func}")

    if has_high:
        print("❌ Blocking: HIGH risk API changes detected")
        return 1

    if has_unknown and block_unknown:
        print("❌ Blocking: UNKNOWN risk API changes detected (block_unknown=true)")
        return 1

    if has_unknown:
        print("⚠️ Warning: Unknown risk areas detected")

    print("✅ API risk acceptable")
    return 0
