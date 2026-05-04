import ast
import json
import sys
from pathlib import Path
from typing import Any

# ImpactGuard signature extractor


def serialize_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file: str,
    class_name: str | None = None,
) -> dict[str, Any]:
    """Serialize a function/method node to signature dict.

    Args:
        node: Function AST node.
        file: File path for fqname.
        class_name: Optional class name if this is a method.
    """
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

    # Build fqname with class context: file:ClassName.method or file:function
    if class_name:
        fqname = f"{file}:{class_name}.{node.name}"
        name = f"{class_name}.{node.name}"
    else:
        fqname = f"{file}:{node.name}"
        name = node.name

    return {
        "fqname": fqname,
        "name": name,
        "file": str(file),
        "lineno": node.lineno,
        "end_lineno": getattr(node, "end_lineno", node.lineno),
        "positional": pos,
        "kwonly": kwonly,
        "vararg": args.vararg is not None,
        "kwarg": args.kwarg is not None,
        "class_name": class_name,
    }


def extract(files: list[str], base_path: str | None = None) -> list[dict[str, Any]]:
    """Extract function signatures from Python files.

    Args:
        files: List of file paths (strings or Path objects).
        base_path: Optional base path to make fqnames relative to.

    Returns:
        List of signature dictionaries with class context.
    """
    all_funcs: list[dict[str, Any]] = []

    for f in files:
        path = Path(f)
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue

        # Compute file name for fqname
        if base_path:
            try:
                fq_file = str(path.relative_to(base_path))
            except ValueError:
                fq_file = path.name
        else:
            fq_file = path.name

        # Use a proper visitor to track class context
        class ContextVisitor(ast.NodeVisitor):
            def __init__(self):
                self.current_class: str | None = None
                self.functions: list[dict[str, Any]] = []

            def visit_ClassDef(self, node: ast.ClassDef):
                old_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_class

            def visit_FunctionDef(self, node: ast.FunctionDef):
                self.functions.append(
                    serialize_function(node, fq_file, self.current_class)
                )
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                self.functions.append(
                    serialize_function(node, fq_file, self.current_class)
                )
                self.generic_visit(node)

        visitor = ContextVisitor()
        visitor.visit(tree)
        all_funcs.extend(visitor.functions)

    # stable ordering
    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs
