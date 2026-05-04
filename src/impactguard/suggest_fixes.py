from typing import Any


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
    try:
        lines = open(file).read().splitlines()
        if 0 <= lineno - 1 < len(lines):
            return lines[lineno - 1]
    except Exception:
        pass
    return ""


def enrich_with_fixes(
    report_item: dict[str, Any], _issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:  # noqa: ARG001
    fixes: list[dict[str, Any]] = []

    patches = report_item.get("patches", [])
    if patches:
        fixes.append(
            {"type": "make_optional", "patch": patches[0] if patches else None}
        )

    callsite_patches = report_item.get("callsite_patches", [])
    if callsite_patches:
        fixes.append({"type": "update_calls", "patches": callsite_patches})

    return fixes
