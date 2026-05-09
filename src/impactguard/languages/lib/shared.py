"""Shared utilities for language extractors.

This module contains functions that were previously duplicated across all
language extractor files in the languages/ directory.
"""

import re
import warnings
from pathlib import Path
from typing import Any

# Constants
_IGNORE_TAG = "impactguard: ignore"


# ── Helper functions (previously duplicated 12+ times each) ──────────────────


def node_text(node: Any, source: bytes) -> str:
    """Return the UTF-8 text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def child_of_type(node: Any, *types: str) -> Any | None:
    """Return the first direct child whose type is in *types*, or *None*."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def has_ignore_comment_fallback(lines: list[str], lineno: int) -> bool:
    """Check for ``// impactguard: ignore`` on or before *lineno* (1-based)."""
    for idx in (lineno - 2, lineno - 1):
        if 0 <= idx < len(lines) and _IGNORE_TAG in lines[idx]:
            return True
    return False


def has_ignore_comment(source_bytes: bytes, lineno_0based: int) -> bool:
    """Check for ignore comment using tree-sitter node position (0-based line)."""
    lines = source_bytes.decode("utf-8", errors="replace").splitlines()
    return has_ignore_comment_fallback(lines, lineno_0based + 1)


# ── Common regex patterns (previously duplicated 12 times each) ──────────────

# Matches function calls: ``name(args)``
call_re = re.compile(r"\b(?P<name>\w+)\s*\((?P<args>[^)]*)\)")

# Language-specific keywords (override in language files as needed)
_COMMON_KEYWORDS: frozenset[str] = frozenset()


# ── Tree-sitter parser factory ─────────────────────────────────────────────

_TREE_SITTER_AVAILABLE = False
try:
    from tree_sitter import Language, Parser

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    pass


def make_parser(language_name: str, language_object: Any) -> Any:
    """Create a tree-sitter parser for the given language.

    Args:
        language_name: Human-readable language name (for warning messages)
        language_object: The tree-sitter language object (e.g., tree_sitter_java.language())

    Returns:
        Configured Parser instance, or None if tree-sitter is not available
    """
    if not _TREE_SITTER_AVAILABLE:
        return None
    try:
        from tree_sitter import Parser

        parser = Parser(language_object)
        return parser
    except Exception as e:
        warnings.warn(f"Failed to create {language_name} parser: {e}", stacklevel=2)
        return None


# ── Registration helper (previously duplicated 13 times) ───────────────────


def register_extractor(extractor_instance: Any) -> None:
    """Register a language extractor with the ImpactGuard registry.

    Args:
        extractor_instance: Instance of the language extractor class
    """
    from .registry import register

    register(extractor_instance)


# ── Warning helpers ────────────────────────────────────────────────────────


def warn_if_no_tree_sitter(self: Any, language_name: str, package_name: str) -> None:
    """Warn if tree-sitter is not available (calls warn only once).

    Note: The caller should check the language-specific availability flag
    before calling this function.

    Args:
        self: The extractor instance (checks/stores self._warned)
        language_name: Human-readable language name (e.g., "Java")
        package_name: PyPI package name (e.g., "tree-sitter-java")
    """
    if not getattr(self, "_warned", False):
        warnings.warn(
            f"tree-sitter and {package_name} are not installed; "
            f"{language_name} extraction will use a regex-based fallback which "
            "may miss some function signatures.  Install the 'languages' "
            "extra for full support:  pip install 'impactguard[languages]'",
            UserWarning,
            stacklevel=3,
        )
        self._warned = True


# ── Signature dictionary constructor ──────────────────────────────────────


def make_signature_dict(
    fqname: str,
    display_name: str,
    file: str,
    lineno: int,
    end_lineno: int,
    positional: list[dict[str, Any]],
    has_vararg: bool,
    class_name: str | None,
    return_type: str | None,
    is_async: bool,
    ignored: bool,
    exported: bool,
) -> dict[str, Any]:
    """Create a standardized signature dictionary.

    This replaces the duplicated dict construction previously found in all
    language extractor files.
    """
    return {
        "fqname": fqname,
        "name": display_name,
        "file": file,
        "lineno": lineno,
        "end_lineno": end_lineno,
        "positional": positional,
        "kwonly": [],
        "vararg": has_vararg,
        "kwarg": False,
        "class_name": class_name,
        "return_type": return_type,
        "decorators": [],
        "is_async": is_async,
        "ignored": ignored,
        "exported": exported,
    }


# ── Call dictionary constructor ────────────────────────────────────────────


def make_call_dict(
    name: str,
    lineno: int,
    arg_count: int,
    file: str,
) -> dict[str, Any]:
    """Create a standardized call-site dictionary.

    This replaces the duplicated dict construction previously found in all
    language extractor files.
    """
    return {
        "name": name,
        "lineno": lineno,
        "args": arg_count,
        "kwargs": [],
        "has_starargs": False,
        "has_kwargs": False,
        "file": file,
    }


def _extract_call_name(
    node: Any,
    source: bytes,
    member_map: dict[str, str | None] | None = None,
    ident_type: str | None = None,
) -> str | None:
    """Extract the call name from a function node.

    Handles simple identifiers (returns the text) and member expressions
    using *member_map* to resolve the relevant child field.
    When *member_map* maps a node type to a field name, only that field's
    text is returned.  When mapped to ``None``, all named children are
    joined with ``.``.
    *ident_type* overrides the default ``"identifier"`` type check.
    """
    member_map = member_map or {}
    target = ident_type or "identifier"
    if node.type == target:
        return node_text(node, source)
    if node.type in member_map:
        rhs_field = member_map[node.type]
        if rhs_field is not None:
            for child in node.named_children:
                if child.type == rhs_field:
                    return node_text(child, source)
            return None
        return ".".join(node_text(c, source) for c in node.named_children)
    if node.named_children:
        return _extract_call_name(
            node.named_children[0], source, member_map, ident_type
        )
    return None


def extract_calls_with_tree_sitter(
    path: Path,
    language_name: str,
    language_object: Any,
    *,
    call_type: str = "call_expression",
    name_on_call: bool = False,
    fallback_ident: bool = False,
    member_map: dict[str, str | None] | None = None,
    args_type: str = "argument_list",
    ident_type: str | None = None,
    count_args: str = "named",
    count_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Extract call sites from a file using tree-sitter.

    Args:
        path: Path to the source file.
        language_name: Human-readable name (for error messages).
        language_object: Tree-sitter Language object.
        call_type: AST node type for call expressions.
        name_on_call: When *True*, the function name is stored in a
            named child of the call node (tried via ``child_by_field_name("name")``,
            then ``child_by_field_name("method")``).
        fallback_ident: When *True* and no name found via *name_on_call*,
            scan named children for the first identifier.
        member_map: Maps member-expression AST types to the child field
            type used for the right-hand side (e.g., ``"field_identifier"``).
            Map to ``None`` to join all named children with ``.``.
        args_type: AST node type for the argument list.
        ident_type: Node type for identifiers (e.g., ``"simple_identifier"``,
            ``"variable"``).  When *None*, uses ``"identifier"``.
        count_args: How to count arguments:
            - ``"named"`` — count ``named_children`` of the args node.
            - ``"include"`` — count children whose type is in *count_types*.
            - ``"arithmetic"`` — for Haskell ``apply``: named_children - 1.
        count_types: Set of child types to count when *count_args* is ``"include"``.

    Returns:
        List of call-site dictionaries.
    """
    if not _TREE_SITTER_AVAILABLE:
        return []

    parser = make_parser(language_name, language_object)
    if parser is None:
        return []

    try:
        source = path.read_bytes()
    except OSError:
        return []

    tree = parser.parse(source)
    calls: list[dict[str, Any]] = []

    def _first_ident(node: Any) -> str | None:
        """Return text of the first identifier-like child of *node*."""
        target = ident_type or "identifier"
        for child in node.named_children:
            if child.type == target:
                return node_text(child, source)
            deeper = _first_ident(child)
            if deeper is not None:
                return deeper
        return None

    def visit(node: Any) -> None:
        if node.type == call_type:
            name: str | None = None
            if name_on_call:
                for field in ("name", "method"):
                    n = node.child_by_field_name(field)
                    if n is not None:
                        name = node_text(n, source)
                        break
                if name is None and fallback_ident:
                    name = _first_ident(node)
            else:
                func_node = node.child_by_field_name("function")
                if func_node is None and node.named_children:
                    func_node = node.named_children[0]
                if func_node is not None:
                    name = _extract_call_name(func_node, source, member_map, ident_type)

            if name is not None:
                if count_args == "arithmetic":
                    arg_count = max(0, len(node.named_children) - 1)
                else:
                    args_node = node.child_by_field_name("arguments")
                    if args_node is None:
                        for child in node.named_children:
                            if child.type == args_type:
                                args_node = child
                                break
                    if args_node is None and node.named_children:
                        args_node = node.named_children[-1]

                    arg_count = 0
                    if args_node is not None:
                        if count_args == "include":
                            types = count_types or set()
                            if types:
                                for child in args_node.children:
                                    if child.type in types:
                                        arg_count += 1
                            else:
                                for child in args_node.named_children:
                                    if child.type != ",":
                                        arg_count += 1
                        else:
                            for child in args_node.named_children:
                                if child.type != ",":
                                    arg_count += 1

                lineno = node.start_point[0] + 1
                calls.append(make_call_dict(name, lineno, arg_count, str(path)))

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return calls
