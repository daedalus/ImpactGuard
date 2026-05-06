import difflib
from pathlib import Path
from typing import Any


def _is_safe_path(file: str) -> bool:
    """Return True only when *file* is a safe relative path with no traversal."""
    if not file:
        return False
    p = Path(file)
    # Reject absolute paths and path-traversal sequences.
    if p.is_absolute() or ".." in p.parts:
        return False
    return True


def patch_add_default(func: dict[str, Any], param_name: str) -> tuple[str | None, str | None]:
    """Generate patch to add default value to parameter."""
    file = func.get("file", "")
    lineno = func.get("lineno", 0)

    if not file or lineno < 1:
        return None, "Invalid function data"

    if not _is_safe_path(file):
        return None, f"Unsafe file path rejected: {file}"

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

    if not _is_safe_path(file):
        return None, f"Unsafe file path rejected: {file}"

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
