import json
import sys
from typing import Any

from .risk_model import classify, get_severity


def run(
    diff_path: str,
    runtime_path: str,
    output_path: str | None = None,
    lambda_: float = 1.0,
) -> list[dict[str, Any]]:
    """Run risk analysis pipeline.

    Args:
        diff_path: Path to diff text file.
        runtime_path: Path to runtime data JSON.
        output_path: Optional output path for report JSON.
        lambda_: Sensitivity multiplier (default 1.0). Values >1 increase
            sensitivity (more changes flagged HIGH/MEDIUM); values <1 decrease it.

    Returns:
        List of risk report items.
    """
    # Parse diff file
    try:
        with open(diff_path) as f:
            diff_text = f.read()
    except OSError as exc:
        raise OSError(f"Cannot read diff file '{diff_path}': {exc}") from exc

    # Load runtime data
    try:
        with open(runtime_path) as f:
            runtime_data = json.load(f)
        runtime = {item["function"]: item.get("count", 1) for item in runtime_data}
    except Exception:
        runtime = {}

    max_count = max(runtime.values()) if runtime else 1

    # Parse breaking/non-breaking from diff
    report: list[dict[str, Any]] = []

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
            risk, exp, conf = classify(severity, count, max_count, count, lambda_)

            report.append(
                {
                    "function": func_name.strip(),
                    "risk": risk,
                    "change": current_change,
                    "exposure": exp,
                    "confidence": conf,
                    "details": f"called {count} times" if count > 0 else "not observed",
                }
            )

    # Sort by risk level
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}
    report.sort(key=lambda x: risk_order.get(str(x["risk"]), 4))

    if output_path:
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

    return report


def risk_main_cli(
    diff_path: str | None = None,
    runtime_path: str | None = None,
    output_path: str | None = None,
) -> list[dict[str, Any]]:
    """CLI entry point."""
    if diff_path is None:
        if len(sys.argv) < 3:
            print("Usage: python risk_gate.py <diff.txt> <runtime.json> [output.json]")
            sys.exit(1)
        diff_path = sys.argv[1]
        runtime_path = sys.argv[2]
        output_path = sys.argv[3] if len(sys.argv) > 3 else "report.json"

    if runtime_path is None:
        return []

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
