"""JavaScript language extractor for ImpactGuard.

Provides signature and call-site extraction for JavaScript (``.js``, ``.mjs``,
``.cjs``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-javascript`` packages::

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

from ._shared import (
    _IGNORE_TAG,
    _TREE_SITTER_AVAILABLE,
    child_of_type,
    has_ignore_comment,
    has_ignore_comment_fallback,
    make_call_dict,
    make_parser,
    make_signature_dict,
    node_text,
    register_extractor,
    warn_if_no_tree_sitter,
)

# ── Optional tree-sitter dependency ──────────────────────────────────────────

try:
    import tree_sitter_javascript as _js_lang
    from tree_sitter import Language as _JsLanguage
    from tree_sitter import Parser as _JsParser

    _JS_LANGUAGE = _JsLanguage(_js_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _make_parser() -> Any:
    """Create a fresh tree-sitter JavaScript parser."""
    return _JsParser(_JS_LANGUAGE)


def _is_exported(node: Any, _source: bytes) -> bool:
    """Return True if the node or its parent has an export keyword."""
    parent = node.parent
    if parent is not None and parent.type == "export_statement":
        return True
    for child in node.children:
        if child.type == "export":
            return True
    return False


def _is_async_node(node: Any, _source: bytes) -> bool:
    """Return True if the node has an async keyword."""
    for child in node.children:
        if child.type == "async":
            return True
    return False


def _class_name_for_method(node: Any, source: bytes) -> str | None:
    """Walk up the tree to find the enclosing class name."""
    parent = node.parent
    while parent is not None:
        if parent.type == "class_declaration":
            name_node = child_of_type(parent, "identifier")
            if name_node is not None:
                return node_text(name_node, source)
        parent = parent.parent
    return None


def _parse_formal_params(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a JS ``formal_parameters`` node into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type in ("(", ")", ","):
            continue
        if child.type == "rest_pattern":
            has_vararg = True
        elif child.type == "identifier":
            positional.append(
                {"name": node_text(child, source), "has_default": False, "type": None}
            )
        elif child.type == "assignment_pattern":
            # default value: identifier = expr
            id_node = child_of_type(child, "identifier")
            name = node_text(id_node, source) if id_node else "_"
            positional.append({"name": name, "has_default": True, "type": None})
        elif child.type in ("required_parameter", "optional_parameter"):
            # TSX-style, just in case
            id_node = child_of_type(child, "identifier")
            name = node_text(id_node, source) if id_node else "_"
            has_def = child.type == "optional_parameter"
            positional.append({"name": name, "has_default": has_def, "type": None})
        elif child.type not in ("{", "}", "[", "]"):
            # Treat as unnamed param
            text = node_text(child, source).strip()
            if text and text not in (",", "(", ")"):
                positional.append({"name": text, "has_default": False, "type": None})

    return positional, has_vararg


def _process_function(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a function node."""
    name: str | None = None
    class_name: str | None = None

    if node.type == "function_declaration":
        id_node = child_of_type(node, "identifier")
        name = node_text(id_node, source) if id_node else None
    elif node.type == "method_definition":
        prop_node = child_of_type(node, "property_identifier")
        name = node_text(prop_node, source) if prop_node else None
        class_name = _class_name_for_method(node, source)
    elif node.type in ("function", "arrow_function"):
        # Look for variable_declarator parent to get assigned name
        parent = node.parent
        if parent is not None and parent.type == "variable_declarator":
            id_node = child_of_type(parent, "identifier")
            name = node_text(id_node, source) if id_node else None
        if name is None:
            return

    if name is None:
        return

    params_node = child_of_type(node, "formal_parameters")
    positional, has_vararg = _parse_formal_params(params_node, source)
    is_async = _is_async_node(node, source)
    exported = _is_exported(node, source)

    if class_name:
        fqname = f"{fq_file}:{class_name}.{name}"
        display_name = f"{class_name}.{name}"
    else:
        fqname = f"{fq_file}:{name}"
        display_name = name

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
            "return_type": None,
            "decorators": [],
            "is_async": is_async,
            "ignored": has_ignore_comment(source, node.start_point[0]),
            "exported": exported,
        }
    )


def _extract_with_tree_sitter(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract JavaScript signatures using tree-sitter."""
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

        def visit(node: Any) -> None:
            if node.type in (
                "function_declaration",
                "method_definition",
                "function",
                "arrow_function",
            ):
                _process_function(node, source, fq_file, funcs)
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract JavaScript call sites using tree-sitter."""
    parser = _make_parser()
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
                    name = node_text(func_node, source)
                elif func_node.type == "member_expression":
                    prop = child_of_type(func_node, "property_identifier")
                    if prop is not None:
                        name = node_text(prop, source)
            if name is not None:
                args_node = child_of_type(node, "arguments")
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
    r"(?:export\s+)?(?P<async>async\s+)?function\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)",
    re.MULTILINE,
)

_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?P<async>async\s+)?\((?P<params>[^)]*)\)\s*=>",
    re.MULTILINE,
)


def _parse_js_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a JavaScript parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("..."):
            has_vararg = True
            continue
        has_default = "=" in part
        name = part.split("=")[0].strip()
        positional.append({"name": name, "has_default": has_default, "type": None})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort JavaScript signature extraction using regular expressions."""
    all_funcs: list[dict[str, Any]] = []

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
            params_str = m.group("params") or ""
            is_async = bool(m.group("async"))
            lineno = source[: m.start()].count("\n") + 1
            positional, has_vararg = _parse_js_params_regex(params_str)
            exported = bool(
                re.search(
                    r"\bexport\b", source[max(0, m.start() - 20) : m.start() + 10]
                )
            )

            all_funcs.append(
                {
                    "fqname": f"{fq_file}:{name}",
                    "name": name,
                    "file": fq_file,
                    "lineno": lineno,
                    "end_lineno": lineno,
                    "positional": positional,
                    "kwonly": [],
                    "vararg": has_vararg,
                    "kwarg": False,
                    "class_name": None,
                    "return_type": None,
                    "decorators": [],
                    "is_async": is_async,
                    "ignored": has_ignore_comment_fallback(lines, lineno),
                    "exported": exported,
                }
            )

        for m in _ARROW_RE.finditer(source):
            name = m.group("name")
            params_str = m.group("params") or ""
            is_async = bool(m.group("async"))
            lineno = source[: m.start()].count("\n") + 1
            positional, has_vararg = _parse_js_params_regex(params_str)
            exported = bool(
                re.search(
                    r"\bexport\b", source[max(0, m.start() - 20) : m.start() + 10]
                )
            )

            all_funcs.append(
                {
                    "fqname": f"{fq_file}:{name}",
                    "name": name,
                    "file": fq_file,
                    "lineno": lineno,
                    "end_lineno": lineno,
                    "positional": positional,
                    "kwonly": [],
                    "vararg": has_vararg,
                    "kwarg": False,
                    "class_name": None,
                    "return_type": None,
                    "decorators": [],
                    "is_async": is_async,
                    "ignored": has_ignore_comment_fallback(lines, lineno),
                    "exported": exported,
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
    """Best-effort JavaScript call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "for", "while", "switch", "catch", "function"}
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


# ── Public extractor class ────────────────────────────────────────────────────


class JavaScriptExtractor:
    """Language extractor for JavaScript (``.js``, ``.mjs``, ``.cjs``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "javascript"
    extensions: list[str] = [".js", ".mjs", ".cjs"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from JavaScript files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "JavaScript", "tree-sitter-javascript")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a JavaScript file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "JavaScript", "tree-sitter-javascript")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a JavaScript type string into member types.

        Splits on ``|`` for union types.
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────

register_extractor(JavaScriptExtractor())
