"""Swift language extractor for ImpactGuard.

Provides signature and call-site extraction for Swift (``.swift``) source
files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-swift`` packages::

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
    import tree_sitter_swift as _swift_lang
    from tree_sitter import Language as _SwiftLanguage

    _SWIFT_LANGUAGE = _SwiftLanguage(_swift_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _class_name_for_method(node: Any, source: bytes) -> str | None:
    """Walk up the tree to find the enclosing class/struct/extension name."""
    parent = node.parent
    while parent is not None:
        if parent.type in (
            "class_declaration",
            "struct_declaration",
            "extension_declaration",
        ):
            name_node = child_of_type(parent, "type_identifier", "simple_identifier")
            if name_node is not None:
                return node_text(name_node, source)
        parent = parent.parent
    return None


def _has_modifier(node: Any, source: bytes, modifier: str) -> bool:
    """Return True if the node has the given modifier keyword."""
    for child in node.children:
        if node_text(child, source).strip() == modifier:
            return True
        if child.type in ("modifiers", "access_level_modifier", "mutation_modifier"):
            for mod in child.children:
                if node_text(mod, source).strip() == modifier:
                    return True
    return False


def _parse_params(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Swift parameter list node."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type in ("(", ")", ","):
            continue
        if child.type == "parameter":
            # Swift params: [label] name: Type [= default]
            name: str | None = None
            type_str: str | None = None
            has_default = False
            is_variadic = False
            colon_seen = False
            for c in child.children:
                if c.type in ("simple_identifier", "wildcard_pattern"):
                    if name is None:
                        name = node_text(c, source)
                elif c.type == ":":
                    colon_seen = True
                elif colon_seen and c.type not in ("=",) and type_str is None:
                    type_str = node_text(c, source).strip()
                elif c.type == "=":
                    has_default = True
                elif c.type == "...":
                    is_variadic = True
            if is_variadic:
                has_vararg = True
            positional.append(
                {"name": name or "_", "has_default": has_default, "type": type_str}
            )

    return positional, has_vararg


def _process_function(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a Swift function declaration."""
    name_node = child_of_type(node, "simple_identifier")
    if name_node is None and node.type == "init_declaration":
        name = "init"
    elif name_node is not None:
        name = node_text(name_node, source)
    else:
        return

    params_node = child_of_type(node, "parameter_clause", "function_value_parameters")
    positional, has_vararg = _parse_params(params_node, source)

    # Return type: after ->
    return_type: str | None = None
    arrow_seen = False
    for child in node.children:
        if child.type == "->":
            arrow_seen = True
        elif arrow_seen and child.type not in ("{", ";"):
            return_type = node_text(child, source).strip()
            break

    # Check for async modifier (can be a child, or before 'func' in an ERROR node)
    is_async = _has_modifier(node, source, "async")
    if not is_async:
        # Check if there's an 'async' node before this function_declaration
        # (tree-sitter may put it in an ERROR node before the function)
        parent = node.parent
        if parent is not None:
            found_self = False
            for child in parent.children:
                if found_self:
                    break
                if child == node:
                    found_self = True
                elif child.type == "async" or (
                    child.type == "ERROR"
                    and node_text(child, source).strip() == "async"
                ):
                    is_async = True
                    break

    exported = _has_modifier(node, source, "public") or _has_modifier(
        node, source, "open"
    )
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
    """Extract Swift signatures using tree-sitter."""
    parser = make_parser("swift", _SWIFT_LANGUAGE)
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
                "protocol_function_declaration",
                "init_declaration",
            ):
                _process_function(node, source, fq_file, funcs)
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    return extract_calls_with_tree_sitter(
        path, "swift", _SWIFT_LANGUAGE,
        args_type="call_suffix",
        ident_type="simple_identifier",
        member_map={"navigation_expression": None},
        count_args="include",
        count_types={"value_argument"},
    )
# ── Regex fallback ────────────────────────────────────────────────────────────

_FUNC_RE = re.compile(
    r"(?:(?:public|open|internal|private|fileprivate|static|class|override|"
    r"final|async|mutating|nonmutating|dynamic|required|convenience|weak)\s+)*"
    r"func\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
    r"(?:\s*->\s*(?P<return>[^\{]+))?",
    re.MULTILINE,
)


def _parse_swift_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a Swift parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        is_variadic = part.endswith("...")
        if is_variadic:
            has_vararg = True
            part = part[:-3].strip()
        has_default = "=" in part
        # Swift: label name: Type = default
        if ":" in part:
            label_name, _, type_part = part.partition(":")
            tokens = label_name.strip().split()
            name = tokens[-1] if tokens else "_"
            type_str: str | None = type_part.split("=")[0].strip() or None
        else:
            tokens2 = part.split()
            name = tokens2[-1] if tokens2 else "_"
            type_str = None
        positional.append({"name": name, "has_default": has_default, "type": type_str})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort Swift signature extraction using regular expressions."""
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
            positional, has_vararg = _parse_swift_params_regex(params_str)
            match_text = m.group(0)
            func_idx = match_text.index("func")
            modifiers = match_text[:func_idx]
            is_async = bool(re.search(r"\basync\b", modifiers))
            exported = bool(re.search(r"\b(?:public|open)\b", modifiers))

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
    """Best-effort Swift call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {"if", "for", "while", "switch", "guard", "func", "catch"}
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


class SwiftExtractor:
    """Language extractor for Swift (``.swift``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "swift"
    extensions: list[str] = [".swift"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Swift files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "Swift", "tree-sitter-swift")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a Swift file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "Swift", "tree-sitter-swift")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a Swift type string into member types.

        Splits on ``|`` for union/enum types.
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────

register_extractor(SwiftExtractor())
