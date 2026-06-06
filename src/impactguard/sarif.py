"""SARIF output support for ImpactGuard.

Converts risk report data to `SARIF v2.1.0
<https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html>`_ format so
that results can be consumed by GitHub Advanced Security, VS Code, and other
SARIF-aware tooling.
"""

import json
from typing import Any

try:
    from importlib.metadata import version as _import_version

    _VERSION = _import_version("impactguard")
except Exception:
    _VERSION = "0.0.0"

_SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
    "master/Schemata/sarif-schema-2.1.0.json"
)

_RISK_TO_LEVEL: dict[str, str] = {
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "note",
    "UNKNOWN": "none",
}


def _build_rules(
    report_data: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rules: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for item in report_data:
        change = item.get("change", "UNKNOWN_CHANGE")
        if change not in seen:
            risk = item.get("risk", "UNKNOWN")
            level = _RISK_TO_LEVEL.get(risk, "none")
            rules.append(
                {
                    "id": change,
                    "name": change,
                    "shortDescription": {"text": f"{change} API change"},
                    "fullDescription": {
                        "text": f"Detected a {change} change in the API surface."
                    },
                    "defaultConfiguration": {"level": level},
                    "properties": {
                        "risk": risk,
                        "category": "API change",
                    },
                }
            )
            seen[change] = len(rules) - 1
    return rules, seen


def _build_result(item: dict[str, Any], rule_index: int) -> dict[str, Any]:
    func = item.get("function", "unknown")
    change = item.get("change", "")
    risk = item.get("risk", "UNKNOWN")
    level = _RISK_TO_LEVEL.get(risk, "none")
    exp = item.get("exposure", 0)
    conf = item.get("confidence", 0)
    details = item.get("details", "")

    result: dict[str, Any] = {
        "ruleId": change,
        "ruleIndex": rule_index,
        "level": level,
        "message": {"text": f"{risk} — {func}: {change}"},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": func,
                    },
                    "region": {
                        "startLine": 1,
                    },
                }
            }
        ],
        "properties": {
            "exposure": exp,
            "confidence": conf,
        },
    }

    if details:
        result["properties"]["details"] = details

    return result


def generate_sarif(
    report_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert a risk report to SARIF v2.1.0 format.

    Args:
        report_data: List of risk-report dicts (same format as consumed by
            :func:`~impactguard.generate_report.generate_html`).

    Returns:
        A SARIF v2.1.0 log dictionary (call ``json.dumps`` to serialize).
    """
    report_data = [item for item in report_data if isinstance(item, dict)]

    rules, rule_map = _build_rules(report_data)
    results = [
        _build_result(item, rule_map.get(item.get("change", ""), 0))
        for item in report_data
    ]

    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ImpactGuard",
                        "version": _VERSION,
                        "informationUri": "https://github.com/daedalus/ImpactGuard",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def generate_sarif_from_file(
    risk_json_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a SARIF log from a risk report JSON file.

    Args:
        risk_json_path: Path to risk report JSON file.
        output_path: Optional path to write SARIF JSON output.

    Returns:
        SARIF v2.1.0 log dictionary.

    Raises:
        ValueError: If the JSON file cannot be parsed or is not a list.
    """
    try:
        with open(risk_json_path) as f:
            report = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in report file '{risk_json_path}': {exc}"
        ) from exc
    if not isinstance(report, list):
        raise ValueError(
            f"Report file '{risk_json_path}': expected a JSON array, "
            f"got {type(report).__name__}"
        )

    sarif = generate_sarif(report)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(sarif, f, indent=2)

    return sarif
