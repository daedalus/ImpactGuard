"""Rust language extractor for ImpactGuard.

Provides signature and call-site extraction for Rust (``.rs``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-rust`` packages::

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
    import tree_sitter_rust as _rust_lang  # type: ignore[import-untyped]
    from tree_sitter import Language as _RustLanguage
    from tree_sitter import Parser as _RustParser

    _RUST_LANGUAGE = _RustLanguage(_rust_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────

def _make_parser() -> Any:
    """Create a fresh tree-sitter Rust parser."""
    return _RustParser(_RUST_LANGUAGE)


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
    """Return *True* if a ``// impactguard: ignore`` comment appears on or before the node."""
    tag = b"impactguard: ignore"
    lines = source_bytes.split(b"\n")
    for idx in (lineno_0based - 1, lineno_0based):
        if 0 <= idx < len(lines) and tag in lines[idx]:
            return True
    return False


def _is_pub(node: Any, source: bytes) -> bool:
    """Return True if the node has a ``pub`` visibility modifier."""
    vis = _child_of_type(node, "visibility_modifier")
    if vis is None:
        return False
    return _node_text(vis, source).startswith("pub")


def _parse_parameters(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Rust ``parameters`` node into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type == "parameter":
            name: str | None = None
            type_node = None
            colon_seen = False
            for c in child.children:
                if c.type == "identifier" and not colon_seen:
                    name = _node_text(c, source)
                elif c.type == ":":
                    colon_seen = True
                elif colon_seen and type_node is None:
                    type_node = c
            type_str = _node_text(type_node, source).strip() if type_node else None
            positional.append({
                "name": name or "unknown",
                "has_default": False,
                "type": type_str,
            })
        elif child.type == "self_parameter":
            # &self, &mut self, self — skip as a positional but don't count as vararg
            pass
        elif child.type == "variadic_parameter":
            has_vararg = True

    return positional, has_vararg


def _return_type_text(node: Any, source: bytes) -> str | None:
    """Extract the return type from a function_item or function_signature_item."""
    # The return type appears after the '->' token
    arrow_seen = False
    for child in node.children:
        if child.type == "->":
            arrow_seen = True
        elif arrow_seen and child.type not in ("block", ";"):
            return _node_text(child, source).strip()
    return None


def _process_function(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a ``function_item`` or ``function_signature_item``."""
    name_node = _child_of_type(node, "identifier")
    if name_node is None:
        return

    name = _node_text(name_node, source)
    params_node = _child_of_type(node, "parameters")
    positional, has_vararg = _parse_parameters(params_node, source)
    return_type = _return_type_text(node, source)
    is_pub = _is_pub(node, source)

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
        "exported": is_pub,
    })


def _extract_with_tree_sitter(
    files: list[str],
    base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract Rust signatures using tree-sitter."""
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

        def visit(node: Any, class_name: str | None = None) -> None:
            t = node.type
            if t == "function_item":
                _process_function(node, source, fq_file, class_name, funcs)
            elif t == "function_signature_item":
                _process_function(node, source, fq_file, class_name, funcs)
            elif t in ("impl_item", "trait_item"):
                # Determine the type name for impl/trait
                type_name: str | None = None
                for child in node.children:
                    if child.type in ("type_identifier",) and type_name is None:
                        type_name = _node_text(child, source)
                decl_list = _child_of_type(node, "declaration_list")
                if decl_list is not None:
                    for child in decl_list.children:
                        visit(child, type_name)
            else:
                for child in node.children:
                    visit(child, class_name)

        visit(tree.root_node)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract Rust call sites using tree-sitter."""
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
                    name = _node_text(func_node, source)
                elif func_node.type == "field_expression":
                    field = _child_of_type(func_node, "field_identifier")
                    if field is not None:
                        name = _node_text(field, source)
                elif func_node.type == "scoped_identifier":
                    # e.g. MyStruct::new
                    for c in reversed(func_node.children):
                        if c.type == "identifier":
                            name = _node_text(c, source)
                            break

            if name is not None:
                args_node = _child_of_type(node, "arguments")
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

_FUNC_RE = re.compile(
    r"(?:pub\s+)?fn\s+(?P<name>\w+)\s*"
    r"(?:<[^>]*>)?\s*"
    r"\((?P<params>[^)]*)\)"
    r"(?:\s*->\s*(?P<return>[^{;]+))?",
    re.MULTILINE,
)

_IGNORE_TAG = "impactguard: ignore"


def _has_ignore_comment_fallback(lines: list[str], lineno: int) -> bool:
    """Check for ``// impactguard: ignore`` on or before *lineno* (1-based)."""
    for idx in (lineno - 2, lineno - 1):
        if 0 <= idx < len(lines) and _IGNORE_TAG in lines[idx]:
            return True
    return False


def _parse_rust_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Rust parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part or part in ("self", "&self", "&mut self"):
            continue
        if "..." in part:
            has_vararg = True
            continue
        if ":" in part:
            name, _, type_ = part.partition(":")
            positional.append({
                "name": name.strip(),
                "has_default": False,
                "type": type_.strip() or None,
            })
        else:
            positional.append({"name": part, "has_default": False, "type": None})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Rust signature extraction using regular expressions."""
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
            positional, has_vararg = _parse_rust_params_regex(params_str)
            exported = bool(source[max(0, m.start() - 5):m.start()].strip().endswith("pub"))
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
                "exported": exported,
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
    """Best-effort Rust call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "while", "for", "match", "fn", "let", "loop"}
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

class RustExtractor:
    """Language extractor for Rust (``.rs``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "rust"
    extensions: list[str] = [".rs"]

    def __init__(self) -> None:
        self._warned: bool = False

    def _warn_if_no_tree_sitter(self) -> None:
        if not _TREE_SITTER_AVAILABLE and not self._warned:
            warnings.warn(
                "tree-sitter and tree-sitter-rust are not installed; "
                "Rust extraction will use a regex-based fallback which "
                "may miss some function signatures.  Install the 'languages' "
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
        """Extract signatures from Rust files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, base_path)
        self._warn_if_no_tree_sitter()
        return _extract_with_regex(files, base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Rust file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        self._warn_if_no_tree_sitter()
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Rust type string into member types.

        Rust does not have union types in the traditional sense; returns a
        singleton frozenset.  If ``|`` appears (e.g. in pattern matching
        contexts), each branch is returned as a separate member.
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────────────────────────────

def _register() -> None:
    from .registry import register
    register(RustExtractor())


_register()
