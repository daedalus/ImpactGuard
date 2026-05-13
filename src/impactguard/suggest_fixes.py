import sys
from pathlib import Path
from typing import Any

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
    except Exception:
        pass
    return ""


def enrich_with_fixes(
    report_item: dict[str, Any], _issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    fixes: list[dict[str, Any]] = []

    # Generate CST-based patches (preferred)
    patches = report_item.get("patches", [])
    if patches:
        fixes.append(
            {
                "type": "make_optional",
                "patch": patches[0] if patches else None,
                "function": report_item.get("function", "unknown"),
            }
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

            level, factors = classify_with_factors(
                target, structural, semantic, complexity
            )

            fixes.append(
                {
                    "type": "update_call",
                    "patch": cp,
                    "confidence": factors,
                    "confidence_level": level,
                    "function": report_item.get("function", "unknown"),
                }
            )

    # If no patches yet, try CST patch
    if not fixes and "function" in report_item:
        try:
            func_name = report_item.get("function", "")
            change = report_item.get("change", "")

            # Try CST patch first
            from .cst_patch import patch_function

            # Find the source file
            file_path = report_item.get("file", "")
            if file_path and Path(file_path).exists():
                source = Path(file_path).read_text()
                param_name = None

                # Extract param name from change description
                if "REMOVED" in change or "REQUIRED" in change:
                    parts = change.split()
                    if parts:
                        param_name = parts[-1].strip("()")

                if param_name:
                    patched, _ = patch_function(
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
                    else:
                        from .patch_generator import patch_add_default

                        func_dict = {
                            "file": file_path,
                            "lineno": report_item.get("lineno", 0),
                            "name": func_name,
                        }
                        gen_patch = patch_add_default(func_dict, param_name)
                        if gen_patch:
                            fixes.append(
                                {
                                    "type": "text_patch",
                                    "patch": gen_patch,
                                    "confidence_level": "LOW",
                                }
                            )
        except Exception:
            pass

    return fixes
