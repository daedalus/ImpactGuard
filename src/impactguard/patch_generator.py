import difflib


def patch_add_default(func, param_name):
    file = func.get("file", "")
    lineno = func.get("lineno", 0)

    if not file or lineno < 1:
        return None

    try:
        lines = open(file).read().splitlines()
        if lineno - 1 >= len(lines):
            return None

        original = lines[lineno - 1]

        if param_name in original:
            modified = original.replace(param_name, f"{param_name}=None", 1)
        else:
            return None

        diff = difflib.unified_diff(
            [original + "\n"],
            [modified + "\n"],
            fromfile=f"a/{file}",
            tofile=f"b/{file}",
        )

        return "".join(diff)
    except Exception:
        return None


def patch_callsite(call, func):
    file = call.get("file", "")
    lineno = call.get("lineno", 0)

    if not file or lineno < 1:
        return None

    try:
        lines = open(file).read().splitlines()
        if lineno - 1 >= len(lines):
            return None

        original = lines[lineno - 1]

        # Naive: append missing arg
        modified = original.rstrip(")") + ", token=...)"  # placeholder

        diff = difflib.unified_diff(
            [original + "\n"],
            [modified + "\n"],
            fromfile=f"a/{file}",
            tofile=f"b/{file}",
        )

        return "".join(diff)
    except Exception:
        return None
