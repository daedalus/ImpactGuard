import difflib
from typing import Any


def patch_add_default(func: dict[str, Any], param_name: str) -> tuple[str | None, str | None]:
    """Generate patch to add default value to parameter."""
    file = func.get("file", "")
    lineno = func.get("lineno", 0)

    if not file or lineno < 1:
        return None, "Invalid function data"

    try:
        lines = open(file).read().splitlines()
        if lineno - 1 >= len(lines):
            return None, "Line number out of range"

        original = lines[lineno - 1]

        if param_name in original:
            modified = original.replace(param_name, f"{param_name}=None", 1)
        else:
            return None, f"Parameter {param_name} not found"

        diff = difflib.unified_diff(
            [original + "\n"],
            [modified + "\n"],
            fromfile=f"a/{file}",
            tofile=f"b/{file}",
        )

        return "".join(diff), None

    except Exception as e:
        return None, str(e)


def patch_call_site(call: dict[str, Any], _func: dict[str, Any]) -> tuple[str | None, str | None]:  # noqa: ARG001
    """Generate patch for call site."""
    file = call.get("file", "")
    lineno = call.get("lineno", 0)

    if not file or lineno < 1:
        return None, "Invalid call data"

    try:
        lines = open(file).read().splitlines()
        if lineno - 1 >= len(lines):
            return None, "Line number out of range"

        original = lines[lineno - 1]

        # Naive: append missing arg
        modified = original.rstrip(")") + ", token=...)"  # placeholder

        diff = difflib.unified_diff(
            [original + "\n"],
            [modified + "\n"],
            fromfile=f"a/{file}",
            tofile=f"b/{file}",
        )

        return "".join(diff), None

    except Exception as e:
        return None, str(e)
