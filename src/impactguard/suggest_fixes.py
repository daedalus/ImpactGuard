import sys
from typing import Any

from .fix_generation import generate_fix_candidates
from ._pathutils import is_safe_path
from .patch_confidence import classify_with_factors


def suggest(func: dict[str, Any], issues: list[dict[str, Any]]) -> list[str]:
    suggestions: list[str] = []

    if not issues:
        return suggestions

    if any(i.get("type") == "missing_args" for i in issues):
        suggestions.append(
            f"Make new parameters optional in {func.get('name', 'function')} (add defaults)"
        )

    if any(i.get("type") == "too_many_args" for i in issues):
        suggestions.append(
            f"Remove extra arguments or add *args to {func.get('name', 'function')}"
        )

    if issues:
        callsites = [f"{i.get('file', '?')}:{i.get('lineno', '?')}" for i in issues[:5]]
        if callsites:
            suggestions.append("Update call sites:\n  " + "\n  ".join(callsites))

    return suggestions


def get_line(file: str, lineno: int) -> str:
    if not is_safe_path(file):
        print(
            f"Warning: impactguard: unsafe file path rejected: '{file}'",
            file=sys.stderr,
        )
        return ""
    try:
        with open(file) as f:
            lines = f.read().splitlines()
        if 0 <= lineno - 1 < len(lines):
            return lines[lineno - 1]
    except OSError:
        pass
    return ""


def _cst_patch_fix(report_item: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate fix candidates using normalized CST/text patch service."""
    try:
        return generate_fix_candidates(report_item)
    except (OSError, ImportError, AttributeError, TypeError):
        return []


def enrich_with_fixes(
    report_item: dict[str, Any], _issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    fixes: list[dict[str, Any]] = []

    patches = report_item.get("patches", [])
    if patches:
        fixes.append(
            {
                "type": "make_optional",
                "patch": patches[0] if patches else None,
                "function": report_item.get("function", "unknown"),
            }
        )

    callsite_patches = report_item.get("callsite_patches", [])
    if callsite_patches:
        for cp in callsite_patches:
            level, factors = classify_with_factors(0.8, 0.9, 0.7, 1.0)
            fixes.append(
                {
                    "type": "update_call",
                    "patch": cp,
                    "confidence": factors,
                    "confidence_level": level,
                    "function": report_item.get("function", "unknown"),
                }
            )

    if not fixes and "function" in report_item:
        fixes.extend(_cst_patch_fix(report_item))

    return fixes
