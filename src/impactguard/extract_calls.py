import ast
import json
import sys
from pathlib import Path


class CallVisitor(ast.NodeVisitor):
    def __init__(self, file):
        self.file = file
        self.calls = []

    def visit_Call(self, node):
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

    def get_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr  # lossy but useful
        return None


def extract(path):
    try:
        tree = ast.parse(path.read_text())
    except Exception:
        return []

    visitor = CallVisitor(str(path))
    visitor.visit(tree)
    return visitor.calls


def main():
    files = sys.argv[1:]
    all_calls = []

    for f in files:
        all_calls.extend(extract(Path(f)))

    print(json.dumps(all_calls, indent=2))


if __name__ == "__main__":
    main()
