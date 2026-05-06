"""C and C++ language extractor for ImpactGuard.

Provides signature and call-site extraction for C (``.c``, ``.h``) and
C++ (``.cpp``, ``.hpp``, ``.cc``, ``.cxx``, ``.hxx``) source files.

Two extraction backends are supported for each language:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter``, ``tree-sitter-c``, and ``tree-sitter-cpp``
  packages::

      pip install "impactguard[languages]"

* **Regex fallback** — lightweight extraction that covers the most common
  patterns without any extra dependencies.  Emits a ``UserWarning`` on first
  use so callers know they are getting best-effort results.

The tree-sitter backends are used automatically whenever the packages are
available at import time.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

# ── Optional tree-sitter dependencies ────────────────────────────────────────

try:
    import tree_sitter_c as _c_lang  # type: ignore[import-untyped]
    from tree_sitter import Language as _CLanguage
    from tree_sitter import Parser as _CParser

    _C_LANGUAGE = _CLanguage(_c_lang.language())
    _C_TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _C_TREE_SITTER_AVAILABLE = False

try:
    import tree_sitter_cpp as _cpp_lang  # type: ignore[import-untyped]
    from tree_sitter import Language as _CppLanguage
    from tree_sitter import Parser as _CppParser

    _CPP_LANGUAGE = _CppLanguage(_cpp_lang.language())
    _CPP_TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CPP_TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _make_c_parser() -> Any:
    """Create a fresh tree-sitter C parser."""
    return _CParser(_C_LANGUAGE)


def _make_cpp_parser() -> Any:
    """Create a fresh tree-sitter C++ parser."""
    return _CppParser(_CPP_LANGUAGE)


def _node_text(node: Any, source: bytes) -> str:
    """Return the UTF-8 text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _child_of_type(node: Any, *types: str) -> Any | None:
    """Return the first direct child whose type is in *types*, or *None*."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _has_ignore_comment(source_bytes: bytes, lineno_0based: int) -> bool:
    """Return *True* if a ``// impactguard: ignore`` comment appears on or before the node."""
    tag = b"impactguard: ignore"
    lines = source_bytes.split(b"\n")
    for idx in (lineno_0based - 1, lineno_0based):
        if 0 <= idx < len(lines) and tag in lines[idx]:
            return True
    return False


def _parse_parameter_list(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a C/C++ ``parameter_list`` node into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type == "parameter_declaration":
            # Find the declarator (name) and type
            name: str | None = None
            type_parts: list[str] = []
            for c in child.children:
                if c.type in ("identifier",):
                    name = _node_text(c, source)
                elif c.type == "pointer_declarator":
                    # *name
                    inner = _child_of_type(c, "identifier")
                    if inner is not None:
                        name = _node_text(inner, source)
                    type_parts.append("*")
                elif c.type not in (",", "(", ")", ";"):
                    type_parts.append(_node_text(c, source).strip())
            type_str = " ".join(t for t in type_parts if t) or None
            positional.append(
                {
                    "name": name or "_",
                    "has_default": False,
                    "type": type_str,
                }
            )
        elif child.type == "variadic_parameter":
            has_vararg = True

    return positional, has_vararg


def _extract_return_type(node: Any, source: bytes) -> str | None:
    """Extract return type from a function_definition or declaration node."""
    # In C/C++ AST: the type specifier(s) appear before the function_declarator
    type_parts: list[str] = []
    for child in node.children:
        if child.type == "function_declarator":
            break
        if child.type not in ("{", "}", ";", "template_declaration"):
            text = _node_text(child, source).strip()
            if text:
                type_parts.append(text)
    return " ".join(type_parts) or None


def _process_function_def(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a ``function_definition`` node (C/C++)."""
    func_decl = _child_of_type(node, "function_declarator")
    if func_decl is None:
        return

    name_node = _child_of_type(
        func_decl,
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
    )
    if name_node is None:
        return

    # For qualified names (A::B), take the last component
    name_text = _node_text(name_node, source)
    if "::" in name_text:
        name_text = name_text.rsplit("::", 1)[-1]

    params_node = _child_of_type(func_decl, "parameter_list")
    positional, has_vararg = _parse_parameter_list(params_node, source)
    return_type = _extract_return_type(node, source)

    if class_name:
        fqname = f"{fq_file}:{class_name}.{name_text}"
        display_name = f"{class_name}.{name_text}"
    else:
        fqname = f"{fq_file}:{name_text}"
        display_name = name_text

    funcs.append(
        {
            "fqname": fqname,
            "name": display_name,
            "file": fq_file,
            "lineno": node.start_point[0] + 1,
            "end_lineno": node.end_point[0] + 1,
            "positional": positional,
            "kwonly": [],
            "vararg": has_vararg,
            "kwarg": False,
            "class_name": class_name,
            "return_type": return_type,
            "decorators": [],
            "is_async": False,
            "ignored": _has_ignore_comment(source, node.start_point[0]),
            "exported": True,
        }
    )


def _process_declaration(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a function signature from a C/C++ declaration (prototype) node."""
    func_decl = _child_of_type(node, "function_declarator")
    if func_decl is None:
        return

    name_node = _child_of_type(func_decl, "identifier", "field_identifier")
    if name_node is None:
        return

    name_text = _node_text(name_node, source)
    params_node = _child_of_type(func_decl, "parameter_list")
    positional, has_vararg = _parse_parameter_list(params_node, source)
    return_type = _extract_return_type(node, source)

    if class_name:
        fqname = f"{fq_file}:{class_name}.{name_text}"
        display_name = f"{class_name}.{name_text}"
    else:
        fqname = f"{fq_file}:{name_text}"
        display_name = name_text

    funcs.append(
        {
            "fqname": fqname,
            "name": display_name,
            "file": fq_file,
            "lineno": node.start_point[0] + 1,
            "end_lineno": node.end_point[0] + 1,
            "positional": positional,
            "kwonly": [],
            "vararg": has_vararg,
            "kwarg": False,
            "class_name": class_name,
            "return_type": return_type,
            "decorators": [],
            "is_async": False,
            "ignored": _has_ignore_comment(source, node.start_point[0]),
            "exported": True,
        }
    )


def _visit_node(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Recursively visit a C/C++ tree-sitter node and collect signatures."""
    t = node.type

    if t == "function_definition":
        _process_function_def(node, source, fq_file, class_name, funcs)
        return

    if t == "declaration":
        _process_declaration(node, source, fq_file, class_name, funcs)
        return

    if t == "class_specifier":
        # Extract class name
        cn: str | None = None
        for child in node.children:
            if child.type == "type_identifier":
                cn = _node_text(child, source)
                break
        body = _child_of_type(node, "field_declaration_list")
        if body is not None:
            for child in body.children:
                _visit_node(child, source, fq_file, cn, funcs)
        return

    if t == "field_declaration":
        # C++ method declarations inside class body
        func_decl = _child_of_type(node, "function_declarator")
        if func_decl is not None:
            _process_declaration(node, source, fq_file, class_name, funcs)
        return

    if t == "template_declaration":
        # Unwrap template and recurse
        for child in node.children:
            if child.type in ("function_definition", "declaration", "class_specifier"):
                _visit_node(child, source, fq_file, class_name, funcs)
        return

    # Default: recurse into all children
    for child in node.children:
        _visit_node(child, source, fq_file, class_name, funcs)


def _extract_with_tree_sitter(
    files: list[str],
    use_cpp: bool,
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract C or C++ signatures using tree-sitter."""
    if use_cpp:
        parser = _make_cpp_parser()
    else:
        parser = _make_c_parser()

    all_funcs: list[dict[str, Any]] = []

    for f in files:
        path = Path(f)
        try:
            source = path.read_bytes()
        except OSError:
            continue

        tree = parser.parse(source)
        fq_file = path.name
        funcs: list[dict[str, Any]] = []
        _visit_node(tree.root_node, source, fq_file, None, funcs)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path, use_cpp: bool) -> list[dict[str, Any]]:
    """Extract C/C++ call sites using tree-sitter."""
    if use_cpp:
        parser = _make_cpp_parser()
    else:
        parser = _make_c_parser()

    try:
        source = path.read_bytes()
    except OSError:
        return []

    tree = parser.parse(source)
    calls: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if node.type == "call_expression":
            func_node = node.children[0] if node.children else None
            name: str | None = None
            if func_node is not None:
                if func_node.type == "identifier":
                    name = _node_text(func_node, source)
                elif func_node.type == "field_expression":
                    field = _child_of_type(func_node, "field_identifier")
                    if field is not None:
                        name = _node_text(field, source)
                elif func_node.type == "qualified_identifier":
                    # A::B — take last component
                    for c in reversed(func_node.children):
                        if c.type in ("identifier", "destructor_name"):
                            name = _node_text(c, source)
                            break

            if name is not None:
                args_node = _child_of_type(node, "argument_list")
                arg_count = 0
                if args_node is not None:
                    arg_count = sum(
                        1 for c in args_node.children if c.type not in ("(", ")", ",")
                    )
                calls.append(
                    {
                        "name": name,
                        "lineno": node.start_point[0] + 1,
                        "args": arg_count,
                        "kwargs": [],
                        "has_starargs": False,
                        "has_kwargs": False,
                        "file": str(path),
                    }
                )

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return calls


# ── Regex fallback ────────────────────────────────────────────────────────────

_FUNC_RE = re.compile(
    r"(?:(?:static|inline|extern|virtual|explicit|constexpr|override|"
    r"const|volatile|unsigned|signed|long|short)\s+)*"
    r"(?P<return>[\w:*&<>\[\]]+(?:\s+[\w:*&<>\[\]]+)*)\s+"
    r"(?P<name>[\w:~]+)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:const\s*)?(?:override\s*)?(?:noexcept\s*)?(?:\w+\s*)?"
    r"[{;]",
    re.MULTILINE,
)

_IGNORE_TAG = "impactguard: ignore"


def _has_ignore_comment_fallback(lines: list[str], lineno: int) -> bool:
    """Check for ``// impactguard: ignore`` on or before *lineno* (1-based)."""
    for idx in (lineno - 2, lineno - 1):
        if 0 <= idx < len(lines) and _IGNORE_TAG in lines[idx]:
            return True
    return False


def _parse_c_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a C/C++ parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str or params_str == "void":
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "...":
            has_vararg = True
            continue
        tokens = part.split()
        if len(tokens) >= 2:
            name = tokens[-1].lstrip("*&").lstrip("*&")
            type_ = " ".join(tokens[:-1])
            positional.append({"name": name, "has_default": False, "type": type_})
        else:
            positional.append({"name": part, "has_default": False, "type": None})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort C/C++ signature extraction using regular expressions."""
    all_funcs: list[dict[str, Any]] = []
    _KEYWORDS = {
        "if",
        "while",
        "for",
        "switch",
        "do",
        "else",
        "return",
        "case",
        "catch",
        "try",
        "new",
        "delete",
        "throw",
    }

    for f in files:
        path = Path(f)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fq_file = path.name
        lines = source.splitlines()

        for m in _FUNC_RE.finditer(source):
            name = m.group("name")
            if name in _KEYWORDS:
                continue
            return_type: str | None = m.group("return").strip() or None
            params_str = m.group("params") or ""
            lineno = source[: m.start()].count("\n") + 1
            positional, has_vararg = _parse_c_params_regex(params_str)
            fqname = f"{fq_file}:{name}"

            all_funcs.append(
                {
                    "fqname": fqname,
                    "name": name,
                    "file": fq_file,
                    "lineno": lineno,
                    "end_lineno": lineno,
                    "positional": positional,
                    "kwonly": [],
                    "vararg": has_vararg,
                    "kwarg": False,
                    "class_name": None,
                    "return_type": return_type,
                    "decorators": [],
                    "is_async": False,
                    "ignored": _has_ignore_comment_fallback(lines, lineno),
                    "exported": True,
                }
            )

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for sig in all_funcs:
        if sig["fqname"] not in seen:
            seen.add(sig["fqname"])
            unique.append(sig)

    unique.sort(key=lambda x: x["fqname"])
    return unique


def _extract_calls_with_regex(path: Path) -> list[dict[str, Any]]:
    """Best-effort C/C++ call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>[\w:]+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "while", "for", "switch", "do", "catch"}
    for m in call_re.finditer(source):
        name = m.group("name")
        if name in _KEYWORDS:
            continue
        args_str = m.group("args").strip()
        arg_count = (
            len([a for a in args_str.split(",") if a.strip()]) if args_str else 0
        )
        lineno = source[: m.start()].count("\n") + 1
        calls.append(
            {
                "name": name,
                "lineno": lineno,
                "args": arg_count,
                "kwargs": [],
                "has_starargs": False,
                "has_kwargs": False,
                "file": str(path),
            }
        )
    return calls


# ── C++ extensions ─────────────────────────────────────────────────────────────

_C_EXTENSIONS = [".c", ".h"]
_CPP_EXTENSIONS = [".cpp", ".hpp", ".cc", ".cxx", ".hxx"]


def _is_cpp_file(path: Path) -> bool:
    return path.suffix.lower() in _CPP_EXTENSIONS


# ── Public extractor classes ──────────────────────────────────────────────────


class CExtractor:
    """Language extractor for C (``.c``, ``.h``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "c"
    extensions: list[str] = _C_EXTENSIONS

    def __init__(self) -> None:
        self._warned: bool = False

    def _warn_if_no_tree_sitter(self) -> None:
        if not _C_TREE_SITTER_AVAILABLE and not self._warned:
            warnings.warn(
                "tree-sitter and tree-sitter-c are not installed; "
                "C extraction will use a regex-based fallback which "
                "may miss some function signatures.  Install the 'languages' "
                "extra for full support:  pip install 'impactguard[languages]'",
                UserWarning,
                stacklevel=3,
            )
            self._warned = True

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from C files."""
        if _C_TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(
                files, use_cpp=False, _base_path=_base_path
            )
        self._warn_if_no_tree_sitter()
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a C file."""
        if _C_TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path, use_cpp=False)
        self._warn_if_no_tree_sitter()
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a C type string into member types (scalar — returns singleton)."""
        return frozenset({type_str.strip()})


class CppExtractor:
    """Language extractor for C++ (``.cpp``, ``.hpp``, ``.cc``, ``.cxx``, ``.hxx``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "cpp"
    extensions: list[str] = _CPP_EXTENSIONS

    def __init__(self) -> None:
        self._warned: bool = False

    def _warn_if_no_tree_sitter(self) -> None:
        if not _CPP_TREE_SITTER_AVAILABLE and not self._warned:
            warnings.warn(
                "tree-sitter and tree-sitter-cpp are not installed; "
                "C++ extraction will use a regex-based fallback which "
                "may miss some function signatures.  Install the 'languages' "
                "extra for full support:  pip install 'impactguard[languages]'",
                UserWarning,
                stacklevel=3,
            )
            self._warned = True

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from C++ files."""
        if _CPP_TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, use_cpp=True, _base_path=_base_path)
        self._warn_if_no_tree_sitter()
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a C++ file."""
        if _CPP_TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path, use_cpp=True)
        self._warn_if_no_tree_sitter()
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a C++ type string into member types (scalar — returns singleton)."""
        return frozenset({type_str.strip()})


# ── Self-registration ─────────────────────────────────────────────────────────


def _register() -> None:
    from .registry import register

    register(CExtractor())
    register(CppExtractor())


_register()
