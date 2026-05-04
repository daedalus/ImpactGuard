from typing import Any

from .patch_confidence import classify_with_factors, compute_confidence
from .cst_patch import patch_function, patch_call

def suggest(
    func: dict[str, Any], issues: list[dict[str, Any]]
) -> list[str]:
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
        callsites = [
            f"{i.get('file', '?')}:{i.get('lineno', '?')}" for i in issues[:5]
        ]
        if callsites:
            suggestions.append("Update call sites:\n  " + "\n  ".join(callsites))

    return suggestions


def get_line(file: str, lineno: int) -> str:
    try:
        lines = open(file).read().splitlines()
        if 0 <= lineno - 1 < len(lines):
            return lines[lineno - 1]
    except Exception:
        pass
    return ""


def enrich_with_fixes(
    report_item: dict[str, Any], _issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    fixes: list[dict[str, Any]] = []

    # Generate CST-based patches
    patches = report_item.get("patches", [])
    if patches:
        fixes.append(
            {"type": "make_optional", "patch": patches[0] if patches else None}
        )

    # Generate confidence-scored fixes
    callsite_patches = report_item.get("callsite_patches", [])
    if callsite_patches:
        for cp in callsite_patches:
            # Compute confidence for each fix
            target = 0.8  # file match
            structural = 0.9  # safe change type
            semantic = 0.7  # based on change type
            complexity = 1.0  # default

            level, factors = classify_with_factors(target, structural, semantic, complexity)

            fixes.append(
                {
                    "type": "update_call",
                    "patch": cp,
                    "confidence": factors,
                    "confidence_level": level,
                }
            )

    # If no patches yet, try generating them with CST
    if not fixes and "function" in report_item:
        func_name = report_item.get("function", "")
        change = report_item.get("change", "")

        # Try to generate CST patch for the function
        try:
            from pathlib import Path

            # Find the source file
            file_path = report_item.get("file", "")
            if file_path and Path(file_path).exists():
                source = Path(file_path).read_text()
                param_name = None

                # Extract param name from change description
                if "REMOVED" in change:
                    # Find which param was removed
                    parts = change.split()
                    if parts:
                        param_name = parts[-1].strip("()")

                if param_name:
                    patched, error = patch_function(
                        source, func_name.split(".")[-1], param_name
                    )
                    if patched:
                        fixes.append(
                            {
                                "type": "cst_patch",
                                "patch": patched,
                                "confidence_level": "MEDIUM",
                            }
                        )
        except Exception:
            pass

    return fixes
