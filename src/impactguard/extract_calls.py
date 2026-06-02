import ast
from pathlib import Path
from typing import Any

from ._ast_cache import cached_ast_parse, cached_read_text


class CallVisitor(ast.NodeVisitor):
    def __init__(self, file: str) -> None:
        self.file = file
        self.calls: list[dict[str, Any]] = []
        self._current_func: str | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev = self._current_func
        self._current_func = node.name
        self.generic_visit(node)
        self._current_func = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        prev = self._current_func
        self._current_func = node.name
        self.generic_visit(node)
        self._current_func = prev

    def visit_Call(self, node: ast.Call) -> None:
        name = self.get_name(node.func)

        if name:
            self.calls.append(
                {
                    "name": name,
                    "lineno": node.lineno,
                    "args": len(node.args),
                    "kwargs": [kw.arg for kw in node.keywords if kw.arg],
                    "has_starargs": any(isinstance(a, ast.Starred) for a in node.args),
                    "has_kwargs": any(kw.arg is None for kw in node.keywords),
                    "file": self.file,
                    "caller": self._current_func,
                }
            )

        self.generic_visit(node)

    def get_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr  # lossy but useful
        return None


def extract(path: Path) -> list[dict[str, Any]]:
    try:
        source_text = cached_read_text(path)
        tree = cached_ast_parse(source_text)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []

    visitor = CallVisitor(str(path))
    visitor.visit(tree)
    return visitor.calls
