"""C# language extractor for ImpactGuard.

Provides signature and call-site extraction for C# (``.cs``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-c-sharp`` packages::

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
    import tree_sitter_c_sharp as _csharp_lang
    from tree_sitter import Language as _CSharpLanguage
    from tree_sitter import Parser as _CSharpParser

    _CSHARP_LANGUAGE = _CSharpLanguage(_csharp_lang.language())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _make_parser() -> Any:
    """Create a fresh tree-sitter C# parser."""
    return _CSharpParser(_CSHARP_LANGUAGE)


def _class_name_for_member(node: Any, source: bytes) -> str | None:
    """Walk up the tree to find the enclosing class/struct/interface name."""
    parent = node.parent
    while parent is not None:
        if parent.type in (
            "class_declaration",
            "struct_declaration",
            "interface_declaration",
            "record_declaration",
        ):
            name_node = child_of_type(parent, "identifier")
            if name_node is not None:
                return node_text(name_node, source)
        parent = parent.parent
    return None


def _has_modifier(node: Any, source: bytes, modifier: str) -> bool:
    """Return True if the node has the given modifier."""
    for child in node.children:
        if child.type == "modifier_list":
            for mod in child.children:
                if node_text(mod, source).strip() == modifier:
                    return True
        elif child.type in ("modifier",):
            if node_text(child, source).strip() == modifier:
                return True
    # Also check direct children for modifier keywords
    for child in node.children:
        txt = node_text(child, source).strip()
        if txt == modifier:
            return True
    return False


def _parse_params(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a C# parameter list node."""
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
            has_default = False
            is_params = False
            for c in child.children:
                if c.type == "identifier":
                    name = node_text(c, source)
                elif c.type in (
                    "predefined_type",
                    "identifier",
                    "generic_name",
                    "nullable_type",
                    "array_type",
                    "qualified_name",
                ):
                    if type_str is None:
                        type_str = node_text(c, source).strip()
                elif c.type == "equals_value_clause":
                    has_default = True
                elif node_text(c, source).strip() == "params":
                    is_params = True
            if is_params:
                has_vararg = True
            positional.append(
                {"name": name or "_", "has_default": has_default, "type": type_str}
            )

    return positional, has_vararg


def _process_method(
    node: Any,
    source: bytes,
    fq_file: str,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract a signature from a C# method/constructor/local function."""
    if node.type in ("method_declaration", "local_function_statement"):
        name_node = child_of_type(node, "identifier")
        if name_node is None:
            return
        name = node_text(name_node, source)

        # Return type is the type before the identifier
        return_type: str | None = None
        for c in node.children:
            if c == name_node:
                break
            txt = node_text(c, source).strip()
            if c.type not in ("modifier",) and txt not in (
                "public",
                "private",
                "protected",
                "internal",
                "static",
                "virtual",
                "override",
                "abstract",
                "sealed",
                "async",
                "new",
                "extern",
                "readonly",
                "unsafe",
                "volatile",
            ):
                if txt:
                    return_type = txt

    elif node.type == "constructor_declaration":
        name_node = child_of_type(node, "identifier")
        if name_node is None:
            return
        name = node_text(name_node, source)
        return_type = None
    else:
        return

    params_node = child_of_type(node, "parameter_list")
    positional, has_vararg = _parse_params(params_node, source)
    is_async = _has_modifier(node, source, "async")
    exported = _has_modifier(node, source, "public")
    class_name = _class_name_for_member(node, source)

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
    """Extract C# signatures using tree-sitter."""
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
                "method_declaration",
                "constructor_declaration",
                "local_function_statement",
            ):
                _process_method(node, source, fq_file, funcs)
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract C# call sites using tree-sitter."""
    parser = _make_parser()
    try:
        source = path.read_bytes()
    except OSError:
        return []

    tree = parser.parse(source)
    calls: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if node.type == "invocation_expression":
            func_node = node.children[0] if node.children else None
            name: str | None = None
            if func_node is not None:
                if func_node.type == "identifier":
                    name = node_text(func_node, source)
                elif func_node.type == "member_access_expression":
                    for c in reversed(func_node.children):
                        if c.type == "identifier":
                            name = node_text(c, source)
                            break
            if name is not None:
                args_node = child_of_type(node, "argument_list")
                arg_count = 0
                if args_node is not None:
                    arg_count = sum(
                        1 for c in args_node.children if c.type == "argument"
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
    r"(?:(?:public|private|protected|internal|static|virtual|override|abstract|"
    r"sealed|async|new|extern|readonly|unsafe|partial)\s+)*"
    r"(?P<return>[\w<>\[\]?,\s\.]+?)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
    r"(?:\s*(?:where\s+\w+\s*:\s*\w+)?)",
    re.MULTILINE,
)


def _parse_csharp_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a C# parameter string into positional args and vararg flag."""
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        is_params = part.startswith("params ")
        if is_params:
            has_vararg = True
            part = part[7:].strip()
        has_default = "=" in part
        part_no_default = part.split("=")[0].strip()
        tokens = part_no_default.split()
        if len(tokens) >= 2:
            name = tokens[-1]
            type_str: str | None = " ".join(tokens[:-1])
        else:
            name = tokens[0] if tokens else "_"
            type_str = None
        positional.append({"name": name, "has_default": has_default, "type": type_str})

    return positional, has_vararg


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort C# signature extraction using regular expressions."""
    all_funcs: list[dict[str, Any]] = []

    _CSHARP_KEYWORDS = {
        "if",
        "else",
        "for",
        "foreach",
        "while",
        "do",
        "switch",
        "case",
        "return",
        "new",
        "class",
        "struct",
        "interface",
        "enum",
        "namespace",
        "using",
        "try",
        "catch",
        "finally",
        "throw",
        "lock",
        "checked",
        "unchecked",
        "fixed",
        "sizeof",
        "typeof",
        "default",
        "delegate",
        "event",
        "abstract",
        "override",
        "virtual",
        "static",
        "sealed",
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
            if name in _CSHARP_KEYWORDS:
                continue
            params_str = m.group("params") or ""
            return_type: str | None = (m.group("return") or "").strip() or None
            lineno = source[: m.start()].count("\n") + 1
            positional, has_vararg = _parse_csharp_params_regex(params_str)
            prefix = source[max(0, m.start() - 100) : m.start() + 50]
            is_async = bool(re.search(r"\basync\b", prefix))
            exported = bool(re.search(r"\bpublic\b", prefix))

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
    """Best-effort C# call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    _KEYWORDS = {
        "if",
        "for",
        "foreach",
        "while",
        "switch",
        "catch",
        "lock",
        "checked",
        "unchecked",
        "fixed",
        "sizeof",
        "typeof",
    }
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


class CSharpExtractor:
    """Language extractor for C# (``.cs``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "csharp"
    extensions: list[str] = [".cs"]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from C# files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        warn_if_no_tree_sitter(self, "C#", "tree-sitter-c-sharp")
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a C# file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        warn_if_no_tree_sitter(self, "C#", "tree-sitter-c-sharp")
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse a C# type string.

        C# does not have traditional union types; returns a singleton frozenset.
        """
        return frozenset({type_str.strip()})


# ── Self-registration ─────────────────────────────────

register_extractor(CSharpExtractor())
