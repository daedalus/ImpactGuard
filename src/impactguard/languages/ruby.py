"""Ruby language extractor for ImpactGuard.

Provides signature and call-site extraction for Ruby (``.rb``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-ruby`` packages::

      pip install "impactguard[languages]"

* **Regex fallback** — lightweight extraction that covers the most common
  patterns without any extra dependencies.  Emits a ``UserWarning`` on first
  use so callers know they are getting best-effort results.

The tree-sitter backend is used automatically whenever the packages are
available at import time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .lib.shared import (
    _TREE_SITTER_AVAILABLE,
    child_of_type,
    extract_calls_with_tree_sitter,
    has_ignore_comment,
    has_ignore_comment_fallback,
    make_parser,
    node_text,
    register_extractor,
    warn_if_no_tree_sitter,
)

# ── Optional tree-sitter dependency ──────────────────────────────────────────

try:
    import tree_sitter_ruby as _ruby_lang
    from tree_sitter import Language as _RubyLanguage

    _RUBY_LANGUAGE = _RubyLanguage(_ruby_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _parse_method_parameters(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Ruby ``method_parameters`` node into positional args and splat flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        t = child.type
        if t == "identifier":
            positional.append(
                {
                    "name": node_text(child, source),
                    "has_default": False,
                    "type": None,
                }
            )
        elif t == "optional_parameter":
            name_node = child_of_type(child, "identifier")
            name = node_text(name_node, source) if name_node else "unknown"
            positional.append({"name": name, "has_default": True, "type": None})
        elif t == "splat_parameter":
            has_vararg = True
        elif t == "hash_splat_parameter":
            # **kwargs equivalent — not vararg in Python sense but we flag it
            pass
        elif t == "block_parameter":
            # &block — skip
            pass
        elif t == "keyword_parameter":
            # name: or name: default
            name_node = child_of_type(child, "identifier")
            name = node_text(name_node, source) if name_node else "unknown"
            has_default = any(
                c.type not in ("identifier", ":", ",") for c in child.children
            )
            positional.append({"name": name, "has_default": has_default, "type": None})

    return positional, has_vararg


def _process_method(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a ``method`` node."""
    name: str | None = None
    params_node = None

    for child in node.children:
        if child.type == "identifier" and name is None:
            name = node_text(child, source)
        elif child.type == "method_parameters":
            params_node = child

    if name is None:
        return

    positional, has_vararg = _parse_method_parameters(params_node, source)

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
            "return_type": None,  # Ruby has no type annotations in standard syntax
            "decorators": [],
            "is_async": False,
            "ignored": has_ignore_comment(source, node.start_point[0]),
            "exported": True,
        }
    )


def _process_singleton_method(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a ``singleton_method`` (``def self.name``) node."""
    name: str | None = None
    params_node = None

    for child in node.children:
        if child.type == "identifier" and name is None:
            # The first identifier after '.' is the method name
            # We skip 'self' node (type "self"), then '.', then get the name
            pass
        elif child.type == "method_parameters":
            params_node = child

    # Walk children specifically: self . name params body end
    children_types = [(c.type, c) for c in node.children]
    dot_seen = False
    for ctype, child in children_types:
        if ctype == ".":
            dot_seen = True
        elif dot_seen and ctype == "identifier" and name is None:
            name = node_text(child, source)

    if name is None:
        return

    positional, has_vararg = _parse_method_parameters(params_node, source)
    prefix = f"{class_name}." if class_name else ""

    funcs.append(
        {
            "fqname": f"{fq_file}:{prefix}{name}",
            "name": f"{prefix}{name}",
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
            "is_async": False,
            "ignored": has_ignore_comment(source, node.start_point[0]),
            "exported": True,
        }
    )


def _extract_with_tree_sitter(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract Ruby signatures using tree-sitter."""
    parser = make_parser("ruby", _RUBY_LANGUAGE)
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
            if t == "method":
                _process_method(node, source, fq_file, class_name, funcs)
            elif t == "singleton_method":
                _process_singleton_method(node, source, fq_file, class_name, funcs)
            elif t == "class":
                # Extract class name
                cn: str | None = None
                for child in node.children:
                    if child.type == "constant":
                        cn = node_text(child, source)
                        break
                body = child_of_type(node, "body_statement")
                if body is not None:
                    for child in body.children:
                        visit(child, cn)
            elif t == "module":
                mn: str | None = None
                for child in node.children:
                    if child.type == "constant":
                        mn = node_text(child, source)
                        break
                body = child_of_type(node, "body_statement")
                if body is not None:
                    for child in body.children:
                        visit(child, mn)
            else:
                for child in node.children:
                    visit(child, class_name)

        visit(tree.root_node)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    return extract_calls_with_tree_sitter(
        path, "ruby", _RUBY_LANGUAGE,
        call_type="call",
        name_on_call=True,
        fallback_ident=True,
    )
# ── Regex fallback ────────────────────────────────────────────────────────────

_METHOD_RE = re.compile(
    r"^\s*def\s+(?:self\.)?(?P<name>\w+[?!]?)\s*"
    r"(?:\((?P<params>[^)]*)\))?",
    re.MULTILINE,
)


def _parse_ruby_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Ruby parameter string into positional args and splat flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*") and not part.startswith("**"):
            has_vararg = True
            continue
        if part.startswith("**") or part.startswith("&"):
            continue
        has_default = "=" in part
        name_m = re.match(r"^(\w+[?!]?)(?:\s*:)?", part)
        name = name_m.group(1) if name_m else part
        positional.append({"name": name, "has_default": has_default, "type": None})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Ruby signature extraction using regular expressions."""
    all_funcs: list[dict[str, Any]] = []

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
            params_str = m.group("params") or ""
            lineno = source[: m.start()].count("\n") + 1
            positional, has_vararg = _parse_ruby_params_regex(params_str)
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
                    "return_type": None,
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
    """Best-effort Ruby call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+[?!]?)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "while", "for", "unless", "until", "case", "def", "class"}
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


class RubyExtractor:
    """Language extractor for Ruby (``.rb``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "ruby"
    extensions: list[str] = [".rb"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Ruby files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "Ruby", "tree-sitter-ruby")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Ruby file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "Ruby", "tree-sitter-ruby")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Ruby type string into member types.

        Ruby does not have union types; returns a singleton frozenset.
        Type unions written with ``|`` (e.g. in Sorbet/RBS annotations) are
        split by ``|``.
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────

register_extractor(RubyExtractor())
