"""Kotlin language extractor for ImpactGuard.

Provides signature and call-site extraction for Kotlin (``.kt``, ``.kts``)
source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-kotlin`` packages::

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
    import tree_sitter_kotlin as _kotlin_lang
    from tree_sitter import Language as _KotlinLanguage
    from tree_sitter import Parser as _KotlinParser

    _KOTLIN_LANGUAGE = _KotlinLanguage(_kotlin_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _make_parser() -> Any:
    """Create a fresh tree-sitter Kotlin parser."""
    return _KotlinParser(_KOTLIN_LANGUAGE)


def _has_modifier(node: Any, source: bytes, modifier: str) -> bool:
    """Return True if the node has the given modifier."""
    for child in node.children:
        if child.type == "modifiers":
            for mod in child.children:
                if node_text(mod, source).strip() == modifier:
                    return True
        elif child.type in ("modifier", "visibility_modifier", "function_modifier"):
            if node_text(child, source).strip() == modifier:
                return True
    return False


def _class_name_for_method(node: Any, source: bytes) -> str | None:
    """Walk up the tree to find the enclosing class name."""
    parent = node.parent
    while parent is not None:
        if parent.type == "class_declaration":
            name_node = child_of_type(parent, "type_identifier", "identifier")
            if name_node is not None:
                return node_text(name_node, source)
        parent = parent.parent
    return None


def _parse_function_params(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Kotlin ``function_value_parameters`` node."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type in ("(", ")", ","):
            continue
        if child.type == "parameter":
            name_node = child_of_type(child, "identifier")
            name = node_text(name_node, source) if name_node else "_"
            type_node = child_of_type(
                child, "type_reference", "nullable_type", "user_type"
            )
            type_str: str | None = None
            if type_node is not None:
                type_str = node_text(type_node, source).strip()
            # Check for default value
            has_default = any(c.type == "=" for c in child.children)
            # Check for vararg modifier
            is_vararg = _has_modifier(child, source, "vararg")
            if is_vararg:
                has_vararg = True
            positional.append(
                {"name": name, "has_default": has_default, "type": type_str}
            )

    return positional, has_vararg


def _process_function(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a Kotlin function declaration."""
    name_node = child_of_type(node, "identifier")
    if name_node is None:
        return

    name = node_text(name_node, source)
    params_node = child_of_type(node, "function_value_parameters")
    positional, has_vararg = _parse_function_params(params_node, source)

    # Return type
    return_type: str | None = None
    colon_seen = False
    for child in node.children:
        if child.type == ":":
            colon_seen = True
        elif colon_seen and child.type in (
            "type_reference",
            "nullable_type",
            "user_type",
            "function_type",
        ):
            return_type = node_text(child, source).strip()
            break

    is_async = _has_modifier(node, source, "suspend")

    # Kotlin is public by default; private/internal/protected → not exported
    not_exported = any(
        _has_modifier(node, source, m) for m in ("private", "internal", "protected")
    )
    exported = not not_exported

    class_name = _class_name_for_method(node, source)

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
            "return_type": return_type,
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
    """Extract Kotlin signatures using tree-sitter."""
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
            if node.type in ("function_declaration", "anonymous_function"):
                _process_function(node, source, fq_file, funcs)
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract Kotlin call sites using tree-sitter."""
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
                elif func_node.type == "navigation_expression":
                    for c in reversed(func_node.children):
                        if c.type == "identifier":
                            name = node_text(c, source)
                            break
            if name is not None:
                args_node = child_of_type(node, "call_suffix", "value_arguments")
                arg_count = 0
                if args_node is not None:
                    arg_count = sum(
                        1 for c in args_node.children if c.type == "value_argument"
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
    r"(?:(?:private|internal|protected|public|suspend|override|inline|operator|infix|tailrec|external|expect|actual)\s+)*"
    r"fun\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
    r"(?:\s*:\s*(?P<return>[^\{=\n]+))?",
    re.MULTILINE,
)


def _parse_kotlin_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Kotlin parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        is_vararg = part.startswith("vararg ")
        if is_vararg:
            has_vararg = True
            part = part[7:].strip()
        has_default = "=" in part
        if ":" in part:
            name_part, _, type_part = part.partition(":")
            name = name_part.strip().split()[-1]
            type_str: str | None = type_part.split("=")[0].strip() or None
        else:
            name = part.split("=")[0].strip()
            type_str = None
        positional.append({"name": name, "has_default": has_default, "type": type_str})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Kotlin signature extraction using regular expressions."""
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
            positional, has_vararg = _parse_kotlin_params_regex(params_str)
            match_text = m.group(0)
            fun_idx = match_text.index("fun")
            modifiers = match_text[:fun_idx]
            is_async = bool(re.search(r"\bsuspend\b", modifiers))
            not_exported = bool(
                re.search(r"\b(?:private|internal|protected)\b", modifiers)
            )
            exported = not not_exported

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
    """Best-effort Kotlin call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "for", "while", "when", "fun", "class", "object", "catch"}
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


class KotlinExtractor:
    """Language extractor for Kotlin (``.kt``, ``.kts``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "kotlin"
    extensions: list[str] = [".kt", ".kts"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Kotlin files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "Kotlin", "tree-sitter-kotlin")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Kotlin file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "Kotlin", "tree-sitter-kotlin")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Kotlin type string into member types.

        Splits on ``|`` (nullable ``T?`` becomes ``T | null``).
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────────────

register_extractor(KotlinExtractor())
