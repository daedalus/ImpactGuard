def suggest(func, issues):
    suggestions = []

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


def get_line(file, lineno):
    try:
        lines = open(file).read().splitlines()
        if 0 <= lineno - 1 < len(lines):
            return lines[lineno - 1]
    except Exception:
        pass
    return ""


def enrich_with_fixes(report_item, issues):
    fixes = []

    patches = report_item.get("patches", [])
    if patches:
        fixes.append(
            {"type": "make_optional", "patch": patches[0] if patches else None}
        )

    callsite_patches = report_item.get("callsite_patches", [])
    if callsite_patches:
        fixes.append({"type": "update_calls", "patches": callsite_patches})

    return fixes
