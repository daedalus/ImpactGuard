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
from pathlib import Path
from typing import Any

from .lib.shared import (
    child_of_type,
    extract_calls_with_tree_sitter,
    has_ignore_comment,
    has_ignore_comment_fallback,
    make_parser,
    node_text,
    register_extractor,
    warn_if_no_tree_sitter,
)

# ── Optional tree-sitter dependencies ────────────────────────────────────────

try:
    import tree_sitter_c as _c_lang
    from tree_sitter import Language as _CLanguage

    _C_LANGUAGE = _CLanguage(_c_lang.language())
    _C_TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _C_TREE_SITTER_AVAILABLE = False

try:
    import tree_sitter_cpp as _cpp_lang
    from tree_sitter import Language as _CppLanguage

    _CPP_LANGUAGE = _CppLanguage(_cpp_lang.language())
    _CPP_TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CPP_TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


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
                    name = node_text(c, source)
                elif c.type == "pointer_declarator":
                    # *name
                    inner = child_of_type(c, "identifier")
                    if inner is not None:
                        name = node_text(inner, source)
                    type_parts.append("*")
                elif c.type not in (",", "(", ")", ";"):
                    type_parts.append(node_text(c, source).strip())
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
            text = node_text(child, source).strip()
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
    func_decl = child_of_type(node, "function_declarator")
    if func_decl is None:
        return

    name_node = child_of_type(
        func_decl,
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
    )
    if name_node is None:
        return

    # For qualified names (A::B), take the last component
    name_text = node_text(name_node, source)
    if "::" in name_text:
        name_text = name_text.rsplit("::", 1)[-1]

    params_node = child_of_type(func_decl, "parameter_list")
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
            "ignored": has_ignore_comment(source, node.start_point[0]),
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
    func_decl = child_of_type(node, "function_declarator")
    if func_decl is None:
        return

    name_node = child_of_type(func_decl, "identifier", "field_identifier")
    if name_node is None:
        return

    name_text = node_text(name_node, source)
    params_node = child_of_type(func_decl, "parameter_list")
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
            "ignored": has_ignore_comment(source, node.start_point[0]),
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
                cn = node_text(child, source)
                break
        body = child_of_type(node, "field_declaration_list")
        if body is not None:
            for child in body.children:
                _visit_node(child, source, fq_file, cn, funcs)
        return

    if t == "field_declaration":
        # C++ method declarations inside class body
        func_decl = child_of_type(node, "function_declarator")
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
        parser = make_parser("C++", _CPP_LANGUAGE)
    else:
        parser = make_parser("C", _C_LANGUAGE)

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


def _extract_calls_with_tree_sitter(
    path: Path, use_cpp: bool,
) -> list[dict[str, Any]]:
    lang_name = "C++" if use_cpp else "C"
    lang_obj = _CPP_LANGUAGE if use_cpp else _C_LANGUAGE
    return extract_calls_with_tree_sitter(
        path, lang_name, lang_obj,
        member_map={
            "field_expression": "field_identifier",
            "qualified_identifier": None,
        },
    )
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
                    "ignored": has_ignore_comment_fallback(lines, lineno),
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



# ── Public extractor classes ──────────────────────────────────────────────────


class CExtractor:
    """Language extractor for C (``.c``, ``.h``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "c"
    extensions: list[str] = _C_EXTENSIONS

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
        warn_if_no_tree_sitter(self, "C", "tree-sitter-c")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a C file."""
        if _C_TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path, use_cpp=False)
        warn_if_no_tree_sitter(self, "C", "tree-sitter-c")
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

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from C++ files."""
        if _CPP_TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, use_cpp=True, _base_path=_base_path)
        warn_if_no_tree_sitter(self, "C++", "tree-sitter-cpp")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a C++ file."""
        if _CPP_TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path, use_cpp=True)
        warn_if_no_tree_sitter(self, "C++", "tree-sitter-cpp")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a C++ type string into member types (scalar — returns singleton)."""
        return frozenset({type_str.strip()})


# ── Self-registration ─────────────────────────────────────────

register_extractor(CExtractor())
register_extractor(CppExtractor())
