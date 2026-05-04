import ast
import json
import sys
from pathlib import Path
from typing import Any

# ImpactGuard signature extractor


def serialize_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, file: str
) -> dict[str, Any]:
    def arg_info(arg: ast.arg, default: object) -> dict[str, Any]:
        return {"name": arg.arg, "has_default": default is not None}

    args = node.args

    pos: list[dict[str, Any]] = []
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
    for a, d in zip(args.args, defaults):
        pos.append(arg_info(a, d))

    kwonly: list[dict[str, Any]] = []
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        kwonly.append(arg_info(a, d))

    return {
        "fqname": f"{file}:{node.name}",
        "name": node.name,
        "file": str(file),
        "lineno": node.lineno,
        "end_lineno": getattr(node, "end_lineno", node.lineno),
        "positional": pos,
        "kwonly": kwonly,
        "vararg": args.vararg is not None,
        "kwarg": args.kwarg is not None,
    }


def extract(files: list[str]) -> list[dict[str, Any]]:
    """Extract function signatures from Python files.

    Args:
        files: List of file paths (strings or Path objects).

    Returns:
        List of signature dictionaries.
    """
    all_funcs: list[dict[str, Any]] = []
    for f in files:
        path = Path(f)
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                all_funcs.append(serialize_function(node, str(path)))

    # stable ordering
    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs
