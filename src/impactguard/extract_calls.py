import ast
import json
import sys
from pathlib import Path
from typing import Any


class CallVisitor(ast.NodeVisitor):
    def __init__(self, file: str) -> None:
        self.file = file
        self.calls: list[dict[str, Any]] = []

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
        tree = ast.parse(path.read_text())
    except Exception:
        return []

    visitor = CallVisitor(str(path))
    visitor.visit(tree)
    return visitor.calls


def main() -> None:
    files = sys.argv[1:]
    all_calls: list[dict[str, Any]] = []

    for f in files:
        all_calls.extend(extract(Path(f)))

    print(json.dumps(all_calls, indent=2))


if __name__ == "__main__":
    main()
