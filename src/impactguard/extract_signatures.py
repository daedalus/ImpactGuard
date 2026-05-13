import ast
import warnings
from pathlib import Path
from typing import Any

from ._logging import get_logger

# ImpactGuard signature extractor
_log = get_logger(__name__)


def _has_ignore_comment(source_lines: list[str], lineno: int) -> bool:
    """Return *True* if a ``# impactguard: ignore`` comment appears on the
    function definition line or on the line immediately preceding it.

    Args:
        source_lines: All lines of the source file (0-indexed list).
        lineno: 1-based line number of the ``def`` keyword.
    """
    tag = "impactguard: ignore"
    def_line_idx = lineno - 1
    for idx in (def_line_idx - 1, def_line_idx):
        if 0 <= idx < len(source_lines) and tag in source_lines[idx]:
            return True
    return False


def _extract_all_names(tree: ast.Module) -> set[str] | None:
    """Return the names listed in ``__all__``, or *None* when not defined.

    Handles only the simple ``__all__ = [...]`` / ``__all__ = (...)`` form.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                val = node.value
                if isinstance(val, ast.List | ast.Tuple):
                    names: set[str] = set()
                    for elt in val.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            names.add(elt.value)
                    return names
    return None


def extract_reexports(files: list[str]) -> dict[str, str]:
    """Parse ``__init__.py`` files and collect explicit re-exports.

    Recognises ``from .<module> import <name>`` and
    ``from .<module> import <name> as <alias>`` statements.

    Args:
        files: List of Python file paths.  Only ``__init__.py`` files are
            processed; all others are ignored.

    Returns:
        Mapping ``{public_fqname: source_fqname}`` where *public_fqname* is
        ``<init_basename>:<exported_name>`` and *source_fqname* is the
        inferred ``<source_module_basename>:<original_name>``.
    """
    reexports: dict[str, str] = {}
    for file_path in files:
        path = Path(file_path)
        if path.name != "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not node.module:
                continue
            # Only relative imports (from .module import ...)
            if node.level == 0:
                continue
            # Source module base name (last segment)
            source_module = node.module.split(".")[-1] + ".py"
            for alias in node.names:
                original = alias.name
                exported = alias.asname or alias.name
                public_fq = f"{path.name}:{exported}"
                source_fq = f"{source_module}:{original}"
                reexports[public_fq] = source_fq

    return reexports


def _unparse_annotation(node: ast.expr | None) -> str | None:
    """Safely unparse an AST annotation node to a string.

    Returns *None* when the node is absent or cannot be unparsed.
    """
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _decorator_name(node: ast.expr) -> str:
    """Return the string representation of a decorator expression."""
    try:
        return ast.unparse(node)
    except Exception:
        return "<decorator>"


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
        return {
            "name": arg.arg,
            "has_default": default is not None,
            "type": _unparse_annotation(arg.annotation),
        }

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

    decorators = [_decorator_name(d) for d in node.decorator_list]
    return_type = _unparse_annotation(node.returns)

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
        "return_type": return_type,
        "decorators": decorators,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
    }


def extract(
    files: list[str],
    _base_path: str | None = None,
    include_reexports: bool = False,
    base_path: str | None = None,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Extract function signatures from Python files.

    Args:
        files: List of file paths (strings or Path objects).
        base_path: Optional base path to make fqnames relative to.
        include_reexports: When *True*, alias signatures are appended for
            names that are re-exported from ``__init__.py`` via relative
            imports.
        strict: When *True*, raise ``SyntaxError`` instead of skipping files
            that fail to parse.  Use this in CI to ensure a broken file is
            never silently ignored.

    Returns:
        List of signature dictionaries with class context.  Each dict includes:

        * ``ignored`` (*bool*) – *True* when a ``# impactguard: ignore``
          comment appears on or immediately before the function definition.
        * ``exported`` (*bool* | *None*) – *True* when the function appears
          in the module's ``__all__`` list, *False* when ``__all__`` is
          defined but does not include this function, *None* when no
          ``__all__`` is defined.
    """
    all_funcs: list[dict[str, Any]] = []

    _log.debug("Extracting signatures from %d file(s)", len(files))

    # Prefer the public `base_path` kwarg; fall back to the legacy `_base_path`.
    effective_base = base_path if base_path is not None else _base_path

    for f in files:
        path = Path(f)
        try:
            source_text = path.read_text()
            tree = ast.parse(source_text)
        except Exception as exc:
            if strict:
                raise RuntimeError(f"ImpactGuard: failed to parse {path}: {exc}") from exc
            _log.warning("Skipping '%s' due to parse error: %s", path, exc)
            warnings.warn(
                f"ImpactGuard: skipping {path} due to parse error: {exc}",
                SyntaxWarning,
                stacklevel=2,
            )
            continue

        # Compute fqname file key: relative to base_path when provided,
        # otherwise fall back to just the filename for cross-directory matching.
        #
        # NOTE — FQN collision risk: two files with the same basename (e.g.
        # a/utils.py and b/utils.py) will produce identical fqnames when no
        # base_path is supplied.  The collision is benign for single-repo use
        # where callers already pass project-relative paths, but can cause
        # ambiguity in monorepos.  Pass ``base_path=<project_root>`` to get
        # stable, collision-free fqnames regardless of working directory.
        if effective_base is not None:
            try:
                fq_file = str(path.relative_to(effective_base))
            except ValueError:
                fq_file = path.name
        else:
            fq_file = path.name
        source_lines = source_text.splitlines()
        all_names: set[str] | None = _extract_all_names(tree)

        # Use a proper visitor to track class context
        class ContextVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.current_class: str | None = None
                self.functions: list[dict[str, Any]] = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                old_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_class

            def _add(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                sig = serialize_function(node, fq_file, self.current_class)
                sig["ignored"] = _has_ignore_comment(source_lines, node.lineno)
                if all_names is not None:
                    leaf = sig["name"].split(".")[-1]
                    sig["exported"] = leaf in all_names
                else:
                    sig["exported"] = None
                self.functions.append(sig)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._add(node)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._add(node)
                self.generic_visit(node)

        visitor = ContextVisitor()
        visitor.visit(tree)
        _log.debug("Extracted %d signature(s) from '%s'", len(visitor.functions), path)
        all_funcs.extend(visitor.functions)

    # Append re-export alias signatures when requested
    if include_reexports:
        reexports = extract_reexports(files)
        by_fqname: dict[str, dict[str, Any]] = {s["fqname"]: s for s in all_funcs}
        for public_fq, source_fq in reexports.items():
            if source_fq in by_fqname and public_fq not in by_fqname:
                alias = dict(by_fqname[source_fq])
                alias["fqname"] = public_fq
                alias["name"] = public_fq.split(":")[-1]
                alias["reexported_from"] = source_fq
                all_funcs.append(alias)

    # stable ordering
    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs
