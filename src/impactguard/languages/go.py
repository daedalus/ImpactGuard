"""Go language extractor for ImpactGuard.

Provides signature and call-site extraction for Go (``.go``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-go`` packages::

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

from .lib.shared import (
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
    import tree_sitter_go as _go_lang
    from tree_sitter import Language as _GoLanguage
    from tree_sitter import Parser as _GoParser

    _GO_LANGUAGE = _GoLanguage(_go_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _make_parser() -> Any:
    """Create a fresh tree-sitter Go parser."""
    return _GoParser(_GO_LANGUAGE)


def _children_of_type(node: Any, *types: str) -> list[Any]:
    """Return all direct children whose type is in *types*."""
    return [c for c in node.children if c.type in types]


def _parse_parameter_list(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Go ``parameter_list`` node into positional args and variadic flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type == "parameter_declaration":
            # May have one or more identifiers followed by a type
            names: list[str] = []
            type_node = None
            for c in child.children:
                if c.type == "identifier":
                    names.append(node_text(c, source))
                elif c.type not in (",", "(", ")"):
                    type_node = c
            type_str = node_text(type_node, source).strip() if type_node else None
            for name in names:
                positional.append(
                    {"name": name, "has_default": False, "type": type_str}
                )
            if not names and type_node is not None:
                # Unnamed parameter
                positional.append({"name": "_", "has_default": False, "type": type_str})

        elif child.type == "variadic_parameter_declaration":
            has_vararg = True
            # Don't add to positional; just mark the flag

    return positional, has_vararg


def _receiver_type(receiver_node: Any, source: bytes) -> str | None:
    """Extract the receiver type name from a receiver parameter list."""
    for child in receiver_node.children:
        if child.type == "parameter_declaration":
            for c in child.children:
                if c.type in ("type_identifier", "pointer_type"):
                    text = node_text(c, source)
                    return text.lstrip("*").strip()
    return None


def _process_function(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a ``function_declaration`` node."""
    name: str | None = None
    params_node = None
    result_node = None

    for child in node.children:
        if child.type == "identifier" and name is None:
            name = node_text(child, source)
        elif child.type == "parameter_list" and params_node is None:
            params_node = child
        elif (
            child.type
            in (
                "type_identifier",
                "pointer_type",
                "parameter_list",
                "map_type",
                "slice_type",
                "array_type",
                "interface_type",
                "qualified_type",
                "generic_type",
            )
            and result_node is None
        ):
            # Result type — appears after the parameter list
            if params_node is not None:
                result_node = child

    if name is None:
        return

    positional, has_vararg = _parse_parameter_list(params_node, source)
    return_type: str | None = None
    if result_node is not None:
        return_type = node_text(result_node, source).strip()

    funcs.append(
        {
            "fqname": f"{fq_file}:{name}",
            "name": name,
            "file": fq_file,
            "lineno": node.start_point[0] + 1,
            "end_lineno": node.end_point[0] + 1,
            "positional": positional,
            "kwonly": [],
            "vararg": has_vararg,
            "kwarg": False,
            "class_name": None,
            "return_type": return_type,
            "decorators": [],
            "is_async": False,
            "ignored": has_ignore_comment(source, node.start_point[0]),
            "exported": bool(name and name[0].isupper()),
        }
    )


def _process_method(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a ``method_declaration`` node."""
    receiver_node = None
    name: str | None = None
    params_nodes: list[Any] = []
    result_node = None

    for child in node.children:
        if child.type == "parameter_list":
            if receiver_node is None and name is None:
                receiver_node = child
            elif len(params_nodes) == 0:
                params_nodes.append(child)
            else:
                result_node = child
        elif child.type == "field_identifier" and name is None:
            name = node_text(child, source)
        elif (
            child.type
            in (
                "type_identifier",
                "pointer_type",
                "map_type",
                "slice_type",
                "qualified_type",
            )
            and result_node is None
        ):
            if params_nodes:
                result_node = child

    if name is None:
        return

    receiver_type = _receiver_type(receiver_node, source) if receiver_node else None
    params_node = params_nodes[0] if params_nodes else None
    positional, has_vararg = _parse_parameter_list(params_node, source)
    return_type: str | None = None
    if result_node is not None:
        return_type = node_text(result_node, source).strip()

    if receiver_type:
        fqname = f"{fq_file}:{receiver_type}.{name}"
        display_name = f"{receiver_type}.{name}"
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
            "class_name": receiver_type,
            "return_type": return_type,
            "decorators": [],
            "is_async": False,
            "ignored": has_ignore_comment(source, node.start_point[0]),
            "exported": bool(name and name[0].isupper()),
        }
    )


def _extract_with_tree_sitter(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract Go signatures using tree-sitter."""
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
            if child.type == "function_declaration":
                _process_function(child, source, fq_file, funcs)
            elif child.type == "method_declaration":
                _process_method(child, source, fq_file, funcs)

        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract Go call sites using tree-sitter."""
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
                elif func_node.type == "selector_expression":
                    field = child_of_type(func_node, "field_identifier")
                    if field is not None:
                        name = node_text(field, source)

            if name is not None:
                args_node = child_of_type(node, "argument_list")
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
    r"^func\s+(?:\([^)]+\)\s+)?(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
    r"(?:\s*(?P<return>[\w\[\]*{},.<> \t]+))?\s*\{",
    re.MULTILINE,
)


def _parse_go_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Go parameter string into positional args and variadic flag."""
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
        tokens = part.split()
        if len(tokens) >= 2:
            name = tokens[0]
            type_ = " ".join(tokens[1:])
            positional.append({"name": name, "has_default": False, "type": type_})
        else:
            positional.append({"name": part, "has_default": False, "type": None})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Go signature extraction using regular expressions."""
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
            return_type: str | None = (m.group("return") or "").strip() or None
            lineno = source[: m.start()].count("\n") + 1
            positional, has_vararg = _parse_go_params_regex(params_str)
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
                    "exported": bool(name and name[0].isupper()),
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
    """Best-effort Go call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "for", "switch", "select", "func", "go", "defer"}
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


class GoExtractor:
    """Language extractor for Go (``.go``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "go"
    extensions: list[str] = [".go"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Go files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "Go", "tree-sitter-go")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Go file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "Go", "tree-sitter-go")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Go type string into member types.

        Go does not have union types; returns a singleton frozenset.
        Interface unions (``A | B``) introduced in Go 1.18 generics are handled
        by splitting on ``|``.
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────

register_extractor(GoExtractor())
