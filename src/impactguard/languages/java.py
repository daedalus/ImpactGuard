"""Java language extractor for ImpactGuard.

Provides signature and call-site extraction for Java (``.java``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-java`` packages::

      pip install "impactguard[languages]"

* **Regex fallback** — lightweight extraction that covers the most common
  patterns without any extra dependencies.  Emits a ``UserWarning`` on first
  use so callers know they are getting best-effort results.

The tree-sitter backend is used automatically whenever the packages are
available at import time.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

# ── Optional tree-sitter dependency ──────────────────────────────────────────

try:
    import tree_sitter_java as _java_lang  # type: ignore[import-untyped]
    from tree_sitter import Language as _JavaLanguage
    from tree_sitter import Parser as _JavaParser

    _JAVA_LANGUAGE = _JavaLanguage(_java_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────

def _make_parser() -> Any:
    """Create a fresh tree-sitter Java parser."""
    return _JavaParser(_JAVA_LANGUAGE)


def _node_text(node: Any, source: bytes) -> str:
    """Return the UTF-8 text of a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child_of_type(node: Any, *types: str) -> Any | None:
    """Return the first direct child whose type is in *types*, or *None*."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _has_ignore_comment(source_bytes: bytes, lineno_0based: int) -> bool:
    """Return *True* if an ``// impactguard: ignore`` comment appears on or before the node."""
    tag = b"impactguard: ignore"
    lines = source_bytes.split(b"\n")
    for idx in (lineno_0based - 1, lineno_0based):
        if 0 <= idx < len(lines) and tag in lines[idx]:
            return True
    return False


def _parse_formal_params(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a ``formal_parameters`` node into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type == "formal_parameter":
            name_node = None
            type_node = None
            for c in child.children:
                if c.type == "identifier":
                    name_node = c
                elif c.type not in ("variable_modifier", ",", ";"):
                    if type_node is None:
                        type_node = c
            name = _node_text(name_node, source) if name_node else "unknown"
            type_str = _node_text(type_node, source).strip() if type_node else None
            positional.append({"name": name, "has_default": False, "type": type_str})

        elif child.type == "spread_parameter":
            # vararg: int... args
            has_vararg = True
            name_node = _child_of_type(child, "variable_declarator")
            if name_node is None:
                # last child is usually the identifier
                for c in reversed(child.children):
                    if c.type == "identifier":
                        name_node = c
                        break
            # Don't add as positional; just mark vararg

    return positional, has_vararg


def _extract_class_methods(
    class_body: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Walk a class_body and extract method_declaration nodes."""
    for child in class_body.children:
        if child.type == "method_declaration":
            _process_method(child, source, fq_file, class_name, funcs)
        elif child.type == "constructor_declaration":
            _process_method(child, source, fq_file, class_name, funcs)
        elif child.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            # Nested types — recurse
            _process_type_decl(child, source, fq_file, funcs)


def _process_method(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a method_declaration or constructor_declaration."""
    name: str | None = None
    params_node = None
    return_type_node = None
    is_constructor = node.type == "constructor_declaration"

    for child in node.children:
        if child.type == "identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "formal_parameters":
            params_node = child
        elif child.type not in (
            "modifiers", "identifier", "formal_parameters",
            "block", "throws", "type_parameters",
            ";", "{", "}",
        ) and return_type_node is None and not is_constructor:
            # The return type is the first non-modifier, non-name child
            return_type_node = child

    if name is None:
        return

    positional, has_vararg = _parse_formal_params(params_node, source)
    return_type: str | None = None
    if return_type_node is not None:
        return_type = _node_text(return_type_node, source).strip()

    if class_name:
        fqname = f"{fq_file}:{class_name}.{name}"
        display_name = f"{class_name}.{name}"
    else:
        fqname = f"{fq_file}:{name}"
        display_name = name

    funcs.append({
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
        "exported": False,
    })


def _process_type_decl(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract methods from a class/interface/enum declaration."""
    class_name: str | None = None
    for child in node.children:
        if child.type in ("identifier", "type_identifier") and class_name is None:
            class_name = _node_text(child, source)

    body = _child_of_type(node, "class_body", "interface_body", "enum_body")
    if body is not None:
        _extract_class_methods(body, source, fq_file, class_name, funcs)


def _extract_with_tree_sitter(
    files: list[str],
    base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract Java signatures using tree-sitter."""
    parser = _make_parser()
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

        for child in tree.root_node.children:
            if child.type in ("class_declaration", "interface_declaration", "enum_declaration"):
                _process_type_decl(child, source, fq_file, funcs)

        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract Java call sites using tree-sitter."""
    parser = _make_parser()
    try:
        source = path.read_bytes()
    except OSError:
        return []

    tree = parser.parse(source)
    calls: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if node.type == "method_invocation":
            # Children: [object '.']? name arguments
            name_node = _child_of_type(node, "identifier")
            if name_node is not None:
                name = _node_text(name_node, source)
                args_node = _child_of_type(node, "argument_list")
                arg_count = 0
                if args_node is not None:
                    arg_count = sum(
                        1 for c in args_node.children
                        if c.type not in ("(", ")", ",")
                    )
                calls.append({
                    "name": name,
                    "lineno": node.start_point[0] + 1,
                    "args": arg_count,
                    "kwargs": [],
                    "has_starargs": False,
                    "has_kwargs": False,
                    "file": str(path),
                })
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return calls


# ── Regex fallback ────────────────────────────────────────────────────────────

# Matches Java method declarations (simplified)
_METHOD_RE = re.compile(
    r"(?:(?:public|private|protected|static|final|abstract|synchronized|native|"
    r"default|strictfp)\s+)*"
    r"(?P<return>\w[\w\.<>\[\],\s]*?)\s+"
    r"(?P<name>\w+)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:throws\s+[\w,\s]+)?\s*[{;]",
    re.MULTILINE,
)

_IGNORE_TAG = "impactguard: ignore"


def _has_ignore_comment_fallback(lines: list[str], lineno: int) -> bool:
    """Check for ``// impactguard: ignore`` on or before *lineno* (1-based)."""
    for idx in (lineno - 2, lineno - 1):
        if 0 <= idx < len(lines) and _IGNORE_TAG in lines[idx]:
            return True
    return False


def _parse_java_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Java parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "..." in part:
            has_vararg = True
            continue
        tokens = part.split()
        if len(tokens) >= 2:
            name = tokens[-1].lstrip("@")
            type_ = " ".join(tokens[:-1])
            positional.append({"name": name, "has_default": False, "type": type_})
        else:
            positional.append({"name": part, "has_default": False, "type": None})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Java signature extraction using regular expressions."""
    all_funcs: list[dict[str, Any]] = []
    _KEYWORDS = {
        "if", "while", "for", "switch", "catch", "try", "do",
        "else", "return", "new", "void",
    }

    for f in files:
        path = Path(f)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fq_file = path.name
        lines = source.splitlines()

        for m in _METHOD_RE.finditer(source):
            name = m.group("name")
            if name in _KEYWORDS:
                continue
            return_type: str | None = m.group("return").strip() or None
            params_str = m.group("params") or ""
            lineno = source[: m.start()].count("\n") + 1
            positional, has_vararg = _parse_java_params_regex(params_str)
            fqname = f"{fq_file}:{name}"

            all_funcs.append({
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
                "exported": False,
            })

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for sig in all_funcs:
        if sig["fqname"] not in seen:
            seen.add(sig["fqname"])
            unique.append(sig)

    unique.sort(key=lambda x: x["fqname"])
    return unique


def _extract_calls_with_regex(path: Path) -> list[dict[str, Any]]:
    """Best-effort Java call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "while", "for", "switch", "catch"}
    for m in call_re.finditer(source):
        name = m.group("name")
        if name in _KEYWORDS:
            continue
        args_str = m.group("args").strip()
        arg_count = len([a for a in args_str.split(",") if a.strip()]) if args_str else 0
        lineno = source[: m.start()].count("\n") + 1
        calls.append({
            "name": name,
            "lineno": lineno,
            "args": arg_count,
            "kwargs": [],
            "has_starargs": False,
            "has_kwargs": False,
            "file": str(path),
        })
    return calls


# ── Public extractor class ────────────────────────────────────────────────────

class JavaExtractor:
    """Language extractor for Java (``.java``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "java"
    extensions: list[str] = [".java"]

    def __init__(self) -> None:
        self._warned: bool = False

    def _warn_if_no_tree_sitter(self) -> None:
        if not _TREE_SITTER_AVAILABLE and not self._warned:
            warnings.warn(
                "tree-sitter and tree-sitter-java are not installed; "
                "Java extraction will use a regex-based fallback which "
                "may miss some method signatures.  Install the 'languages' "
                "extra for full support:  pip install 'impactguard[languages]'",
                UserWarning,
                stacklevel=3,
            )
            self._warned = True

    def extract_signatures(
        self,
        files: list[str],
        base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Java files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, base_path)
        self._warn_if_no_tree_sitter()
        return _extract_with_regex(files, base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Java file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        self._warn_if_no_tree_sitter()
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Java type string into member types.

        Java does not have union types natively; returns a singleton frozenset
        unless the type contains ``|`` (as used in multi-catch clauses).
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────────────────────────────

def _register() -> None:
    from .registry import register
    register(JavaExtractor())


_register()
