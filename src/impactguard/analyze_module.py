import ast
from pathlib import Path
from typing import Any


class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.vars = {}

    def set(self, name, typ):
        self.vars[name] = typ

    def get(self, name):
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        return None


class Analyzer(ast.NodeVisitor):
    def __init__(self, file):
        self.file = file
        self.imports = {}
        self.from_imports = {}
        self.calls = []
        self.scope = Scope()

    # ---------------- imports ----------------

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name
            self.imports[name] = alias.name

    def visit_ImportFrom(self, node):
        mod = node.module or ""
        for alias in node.names:
            name = alias.asname or alias.name
            self.from_imports[name] = f"{mod}.{alias.name}"

    # ---------------- scopes ----------------

    def visit_FunctionDef(self, node):
        prev = self.scope
        self.scope = Scope(parent=prev)

        # arguments with annotations
        for arg in node.args.args:
            if arg.annotation:
                self.scope.set(arg.arg, self._type_name(arg.annotation))

        self.generic_visit(node)
        self.scope = prev

    # ---------------- assignments ----------------

    def visit_AnnAssign(self, node):
        # x: MyClass
        if isinstance(node.target, ast.Name):
            typ = self._type_name(node.annotation)
            if typ:
                self.scope.set(node.target.id, typ)

    def visit_Assign(self, node):
        # x = MyClass() or x = y (alias/reassignment)
        if isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name):
                typ = func.id
                # Track higher-order: my_func = imported_function
                if typ in self.from_imports:
                    typ = self.from_imports[typ]
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.scope.set(target.id, typ)
        # Handle reassignments: x = y (where y has a known type)
        elif isinstance(node.value, ast.Name):
            typ = self.scope.get(node.value.id)
            if typ:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.scope.set(target.id, typ)

    # ---------------- calls ----------------

    def visit_Call(self, node):
        name = self.resolve_call(node.func)

        if name:
            self.calls.append(
                {
                    "fqname": name,
                    "file": self.file,
                    "lineno": node.lineno,
                    "args": len(node.args),
                    "kwargs": [kw.arg for kw in node.keywords if kw.arg],
                    "starargs": any(isinstance(a, ast.Starred) for a in node.args),
                    "kwargs_any": any(kw.arg is None for kw in node.keywords),
                }
            )

        self.generic_visit(node)

    # ---------------- resolution ----------------

    def resolve_call(self, node):
        # foo()
        if isinstance(node, ast.Name):
            if node.id in self.from_imports:
                return self.from_imports[node.id]
            return node.id

        # obj.method()
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                var = node.value.id
                typ = self.scope.get(var)

                if typ:
                    return f"{typ}.{node.attr}"

                # fallback
                return f"{var}.{node.attr}"

            return node.attr

        return None

    # ---------------- helpers ----------------

    def _type_name(self, node):
        """Extract type name from an AST annotation node, handling subscripts."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            # Build full attribute chain: module.Class.method
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))
        if isinstance(node, ast.Subscript):
            # Handle Optional[X], List[Y], Dict[K, V], etc.
            base = self._type_name(node.value)
            return base  # Return base type (e.g., "Optional", "List")
        return None


def analyze(path):
    try:
        tree = ast.parse(Path(path).read_text())
    except Exception:
        return None

    a = Analyzer(path)
    a.visit(tree)

    return {
        "file": path,
        "calls": a.calls,
    }


def analyze_calls(files: list[str]) -> list[dict[str, Any]]:
    """Analyze call sites across multiple Python files.

    Args:
        files: List of Python file paths.

    Returns:
        Flat list of call site dictionaries from all files, each with keys:
        fqname, file, lineno, args, kwargs, starargs, kwargs_any.
    """
    all_calls: list[dict[str, Any]] = []
    for path in files:
        result = analyze(path)
        if result:
            all_calls.extend(result.get("calls", []))

    return all_calls
