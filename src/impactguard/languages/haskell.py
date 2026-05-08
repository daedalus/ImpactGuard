"""Haskell language extractor for ImpactGuard.

Provides signature and call-site extraction for Haskell (``.hs``, ``.lhs``)
source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-haskell`` packages::

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
    import tree_sitter_haskell as _haskell_lang
    from tree_sitter import Language as _HaskellLanguage
    from tree_sitter import Parser as _HaskellParser

    _HASKELL_LANGUAGE = _HaskellLanguage(_haskell_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _make_parser() -> Any:
    """Create a fresh tree-sitter Haskell parser."""
    return _HaskellParser(_HASKELL_LANGUAGE)


def _process_function(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
    type_sigs: dict[str, str],
) -> None:
    """Extract a signature from a Haskell function binding."""
    name_node = node.children[0] if node.children else None
    if name_node is None:
        return

    if name_node.type not in ("variable", "operator"):
        return

    name = node_text(name_node, source)
    return_type = type_sigs.get(name)

    positional: list[dict[str, Any]] = []
    # Patterns after the name are positional parameters
    for c in node.children[1:]:
        if c.type in ("=", "where", "guards"):
            break
        if c.type not in ("|",):
            txt = node_text(c, source).strip()
            if txt:
                positional.append({"name": txt, "has_default": False, "type": None})

    funcs.append(
        {
            "fqname": f"{fq_file}:{name}",
            "name": name,
            "file": fq_file,
            "lineno": node.start_point[0] + 1,
            "end_lineno": node.end_point[0] + 1,
            "positional": positional,
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
            "class_name": None,
            "return_type": return_type,
            "decorators": [],
            "is_async": False,
            "ignored": has_ignore_comment(source, node.start_point[0]),
            "exported": True,
        }
    )


def _extract_with_tree_sitter(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract Haskell signatures using tree-sitter."""
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

        # First pass: collect type signatures
        type_sigs: dict[str, str] = {}

        def collect_sigs(node: Any) -> None:
            if node.type == "type_signature":
                # name :: Type
                parts = node_text(node, source).split("::", 1)
                if len(parts) == 2:
                    sig_name = parts[0].strip()
                    sig_type = parts[1].strip()
                    type_sigs[sig_name] = sig_type
            for child in node.children:
                collect_sigs(child)

        collect_sigs(tree.root_node)

        seen: set[str] = set()

        def find_funcs(node: Any) -> None:
            if node.type in ("function", "bind", "top_splice"):
                _process_function(node, source, fq_file, funcs, type_sigs)
            for child in node.children:
                find_funcs(child)

        find_funcs(tree.root_node)

        # Deduplicate (multiple equations for same function)
        for sig in funcs:
            if sig["fqname"] not in seen:
                seen.add(sig["fqname"])
                all_funcs.append(sig)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract Haskell call sites using tree-sitter."""
    parser = _make_parser()
    try:
        source = path.read_bytes()
    except OSError:
        return []

    tree = parser.parse(source)
    calls: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if node.type == "apply":
            func_node = node.children[0] if node.children else None
            if func_node is not None and func_node.type == "variable":
                name = node_text(func_node, source)
                arg_count = len(node.children) - 1
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

# Match Haskell type signatures: name :: Type
_TYPE_SIG_RE = re.compile(
    r"^(?P<name>[a-z_]\w*(?:')*)\s*::\s*(?P<type>.+)$",
    re.MULTILINE,
)

# Match Haskell function definitions: name args = ...
_FUNC_DEF_RE = re.compile(
    r"^(?P<name>[a-z_]\w*(?:')*)\s+(?P<args>[^=\n]*?)\s*=",
    re.MULTILINE,
)


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Haskell signature extraction using regular expressions."""
    all_funcs: list[dict[str, Any]] = []

    for f in files:
        path = Path(f)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fq_file = path.name
        lines = source.splitlines()

        # Collect type signatures
        type_sigs: dict[str, str] = {}
        for m in _TYPE_SIG_RE.finditer(source):
            type_sigs[m.group("name")] = m.group("type").strip()

        seen: set[str] = set()
        for m in _FUNC_DEF_RE.finditer(source):
            name = m.group("name")
            if name in seen:
                continue
            seen.add(name)
            args_str = (m.group("args") or "").strip()
            lineno = source[: m.start()].count("\n") + 1

            positional: list[dict[str, Any]] = []
            if args_str:
                for arg in args_str.split():
                    positional.append({"name": arg, "has_default": False, "type": None})

            all_funcs.append(
                {
                    "fqname": f"{fq_file}:{name}",
                    "name": name,
                    "file": fq_file,
                    "lineno": lineno,
                    "end_lineno": lineno,
                    "positional": positional,
                    "kwonly": [],
                    "vararg": False,
                    "kwarg": False,
                    "class_name": None,
                    "return_type": type_sigs.get(name),
                    "decorators": [],
                    "is_async": False,
                    "ignored": has_ignore_comment_fallback(lines, lineno),
                    "exported": True,
                }
            )

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_regex(path: Path) -> list[dict[str, Any]]:
    """Best-effort Haskell call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    # Simple heuristic: identifier followed by space-separated args on same line
    call_re = re.compile(r"\b(?P<name>[a-z_]\w*)\s+(?P<args>[^\n=]+)")
    _KEYWORDS = {
        "where",
        "let",
        "in",
        "do",
        "if",
        "then",
        "else",
        "case",
        "of",
        "import",
        "module",
        "data",
        "type",
        "newtype",
        "class",
        "instance",
        "deriving",
    }
    for m in call_re.finditer(source):
        name = m.group("name")
        if name in _KEYWORDS:
            continue
        args_str = m.group("args").strip()
        # Rough arg count: space-separated tokens that don't start with operators
        arg_count = len([a for a in args_str.split() if a and a[0] not in "=->|\\"])
        if arg_count == 0:
            continue
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


class HaskellExtractor:
    """Language extractor for Haskell (``.hs``, ``.lhs``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "haskell"
    extensions: list[str] = [".hs", ".lhs"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Haskell files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "Haskell", "tree-sitter-haskell")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Haskell file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "Haskell", "tree-sitter-haskell")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Haskell type string into member types.

        Splits on ``->`` for function types or ``|`` for sum types.
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        if "->" in s:
            return frozenset(p.strip() for p in s.split("->"))
        return frozenset({s})


# ── Self-registration ─────────────────────────

register_extractor(HaskellExtractor())
