"""Zig language extractor for ImpactGuard.

Provides signature and call-site extraction for Zig (``.zig``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-zig`` packages::

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
    import tree_sitter_zig as _zig_lang
    from tree_sitter import Language as _ZigLanguage

    _ZIG_LANGUAGE = _ZigLanguage(_zig_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _parse_params(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Zig parameter list node."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type in ("(", ")", ","):
            continue
        if child.type == "parameter":
            name: str | None = None
            type_str: str | None = None
            colon_seen = False
            for c in child.children:
                if c.type == "identifier" and not colon_seen:
                    name = node_text(c, source)
                elif c.type == ":":
                    colon_seen = True
                elif colon_seen and type_str is None:
                    type_str = node_text(c, source).strip()
            positional.append(
                {"name": name or "_", "has_default": False, "type": type_str}
            )
        elif child.type == "varargs_parameter":
            has_vararg = True

    return positional, has_vararg


def _process_function(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a Zig function declaration."""
    # Check for pub keyword in parent variable_declaration or directly
    is_pub = False
    parent = node.parent
    if parent is not None:
        for c in parent.children:
            if c.type == "pub" or node_text(c, source).strip() == "pub":
                is_pub = True
                break

    # Also check direct children for pub
    for c in node.children:
        if node_text(c, source).strip() == "pub":
            is_pub = True
            break

    name_node = child_of_type(node, "identifier")
    if name_node is None:
        return

    name = node_text(name_node, source)

    is_async = False
    for c in node.children:
        if node_text(c, source).strip() == "async":
            is_async = True
            break

    params_node = child_of_type(node, "fn_params", "param_list")
    positional, has_vararg = _parse_params(params_node, source)

    # Return type: after params
    return_type: str | None = None
    params_done = False
    for c in node.children:
        if c.type in ("fn_params", "param_list"):
            params_done = True
        elif params_done and c.type not in ("fn", "identifier", "{", ";"):
            txt = node_text(c, source).strip()
            if txt and txt not in (
                "pub",
                "async",
                "extern",
                "export",
                "inline",
                "noinline",
            ):
                return_type = txt
                break

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
            "is_async": is_async,
            "ignored": has_ignore_comment(source, node.start_point[0]),
            "exported": is_pub,
        }
    )


def _extract_with_tree_sitter(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract Zig signatures using tree-sitter."""
    parser = make_parser("zig", _ZIG_LANGUAGE)
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
            if node.type in ("fn_decl", "function_declaration", "function_definition"):
                _process_function(node, source, fq_file, funcs)
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract Zig call sites using tree-sitter."""
    parser = make_parser("zig", _ZIG_LANGUAGE)
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
                elif func_node.type == "field_access":
                    for c in reversed(func_node.children):
                        if c.type == "identifier":
                            name = node_text(c, source)
                            break
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
    r"(?P<pub>pub\s+)?(?:async\s+)?fn\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
    r"(?:\s+(?P<return>[^\{;]+))?",
    re.MULTILINE,
)


def _parse_zig_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Zig parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "...":
            has_vararg = True
            continue
        if ":" in part:
            name, _, type_ = part.partition(":")
            positional.append(
                {
                    "name": name.strip(),
                    "has_default": False,
                    "type": type_.strip() or None,
                }
            )
        else:
            positional.append({"name": part, "has_default": False, "type": None})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Zig signature extraction using regular expressions."""
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
            positional, has_vararg = _parse_zig_params_regex(params_str)
            exported = bool(m.group("pub"))
            prefix = source[max(0, m.start() - 10) : m.start()]
            is_async = bool(re.search(r"\basync\b", prefix))

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
                    "return_type": return_type,
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
    """Best-effort Zig call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "for", "while", "switch", "fn", "catch", "orelse"}
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


class ZigExtractor:
    """Language extractor for Zig (``.zig``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "zig"
    extensions: list[str] = [".zig"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Zig files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "Zig", "tree-sitter-zig")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Zig file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "Zig", "tree-sitter-zig")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Zig type string into member types.

        Splits on `` | `` for tagged union types.
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────

register_extractor(ZigExtractor())
