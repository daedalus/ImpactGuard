"""Shared utilities for language extractors.

This module contains functions that were previously duplicated across all
language extractor files in the languages/ directory.
"""

import logging
import re
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ── Ignore-comment tag ──────────────────────────────────────────────────────

# Allow whitespace/case variations (handles "unusual syntax" per FM #18).
_IGNORE_RE = re.compile(r"impactguard\s*:\s*ignore", re.IGNORECASE)


def _match_ignore_tag(line: str) -> bool:
    """Return *True* if *line* contains an ``impactguard: ignore`` marker."""
    return bool(_IGNORE_RE.search(line))


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
    """Check for ``impactguard: ignore`` on or before *lineno* (1-based)."""
    for idx in (lineno - 2, lineno - 1):
        if 0 <= idx < len(lines) and _match_ignore_tag(lines[idx]):
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
_TreeSitterParser: Any | None = None
try:
    import tree_sitter

    _TreeSitterParser = tree_sitter.Parser
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
    if not _TREE_SITTER_AVAILABLE or _TreeSitterParser is None:
        return None
    try:
        parser = _TreeSitterParser(language_object)
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


# ── Regex fallback — known failure modes per language ─────────────────────
#
# When tree-sitter is absent, each language falls back to regex-based
# extraction.  These patterns are the most common constructs that regex
# cannot reliably handle, listed so users can judge the risk for their
# codebase without installing tree-sitter first.

_REGEX_WEAKNESSES: dict[str, str] = {
    "C": "function pointers, typedef aliases, K&R-style declarations, "
    "nested macros expanding to function-like constructs",
    "C#": "generic methods (Foo<T>), lambda expressions, extension methods, "
    "ref/out/in parameter modifiers, nested partial classes",
    "C++": "templates (including variadic), function-style macros, operator "
    "overloads, lambda expressions, constexpr/consteval specifiers, "
    "SFINAE and enable_if constructs",
    "Go": "generic functions (func Foo[T any]), method receivers on generic "
    "types, embedded interfaces, multiline parameter lists",
    "Haskell": "typeclass constraints in signatures, GADTs, pattern synonym "
    "type signatures, multiline type annotations, fixity declarations",
    "Java": "generic type parameters (<T>), wildcard bounds, annotation-heavy "
    "declarations, default methods in interfaces, varargs combined with "
    "generics, multiline throws clauses",
    "JavaScript": "arrow-function-as-type annotations (JSDoc), `@type` "
    "imports, TS-in-JS typedefs, callable-object signatures, destructured "
    "parameter patterns, variadic catch bindings",
    "Kotlin": "inline/reified type parameters, extension functions with "
    "receiver types, multiline lambda signatures, context receivers, "
    "suspend/operator/infix modifiers, default-parameter expressions",
    "Ruby": "keyword-argument destructuring, block parameters with shadowed "
    "outer variables, multiline parameter spans across `do...end`, method "
    "names with non-alphanumeric characters (!, ?, =), singleton-method "
    "definitions on literals",
    "Rust": "generic type parameters with trait bounds, impl Trait in "
    "argument/return position, lifetime annotations, async fn within impl "
    "blocks, macro-generated functions, const generics, where clauses",
    "Swift": "generic where clauses, opaque result types (some), protocol "
    "associatedtype requirements, multiline parameter labels, inout "
    "parameters, async/await specifiers, closure parameter shorthand",
    "TypeScript": "generic constraints (extends keyof), conditional types, "
    "mapped types, template literal types, overloaded function signatures, "
    "decorators with complex arguments, multiline type annotations",
    "Zig": "comptime parameters, generic function declarations, multiline "
    "parameter lists, function returning error union types, inline/export/"
    "extern calling convention specifiers",
}


def warn_if_no_tree_sitter(self: Any, language_name: str, package_name: str) -> None:
    """Warn if tree-sitter is not available (calls warn only once).

    Includes language-specific known regex failure modes so users can judge
    how incomplete their results might be.

    Note: The caller should check the language-specific availability flag
    before calling this function.

    Args:
        self: The extractor instance (checks/stores self._warned)
        language_name: Human-readable language name (e.g., "Java")
        package_name: PyPI package name (e.g., "tree-sitter-java")
    """
    if not getattr(self, "_warned", False):
        weaknesses = _REGEX_WEAKNESSES.get(language_name, "complex function signatures")
        warnings.warn(
            f"tree-sitter and {package_name} are not installed; "
            f"{language_name} extraction will use a regex-based fallback.\n\n"
            f"Known patterns the regex fallback misses or misparses:\n"
            f"  {weaknesses}\n\n"
            "Install the 'languages' extra for full support:\n"
            "  pip install 'impactguard[languages]'",
            UserWarning,
            stacklevel=3,
        )
        self._warned = True


# ── Regex extraction per-file count logging ────────────────────────────────
#
# Each language has a simple heuristic pattern that counts how many function-
# like definitions *could* be in a file.  When the regex fallback extracts
# significantly fewer, a warning is emitted per file so users know what they
# may be missing.

_log = logging.getLogger("impactguard.languages")

_REGEX_ESTIMATORS: dict[str, re.Pattern] = {
    "C": re.compile(r"\b\w+\s+\w+\s*\("),
    "C#": re.compile(r"(?:public|private|protected|internal|static|)\s*\w+\s+\w+\s*\("),
    "C++": re.compile(r"\b\w+\s+\w+\s*\("),
    "Go": re.compile(r"\bfunc\s+\w+\s*\("),
    "Haskell": re.compile(r"^\s*\w+\s+::", re.MULTILINE),
    "Java": re.compile(r"(?:public|private|protected|static|\w+\s+)\w+\s+\w+\s*\("),
    "JavaScript": re.compile(r"\bfunction\s+\w+\s*\("),
    "Kotlin": re.compile(r"\bfun\s+\w+"),
    "Ruby": re.compile(r"\bdef\s+\w+"),
    "Rust": re.compile(r"\bfn\s+\w+"),
    "Swift": re.compile(r"\bfunc\s+\w+"),
    "TypeScript": re.compile(r"\bfunction\s+\w+\s*\("),
    "Zig": re.compile(r"\bfn\s+\w+"),
}


def log_regex_extraction(
    language_name: str,
    files: list[str],
    result: list[dict[str, Any]],
) -> None:
    """Log per-file regex extraction results with an estimated baseline.

    Groups extracted signatures by file, counts how many the regex extractor
    found per file, and compares against a simple heuristic estimate.  Emits a
    :func:`warnings.warn` when the extracted count is significantly lower than
    the estimate (≤70%), helping users identify files where the regex fallback
    may have missed many signatures.  Otherwise logs at ``INFO`` level.

    Args:
        language_name: Human-readable language name (e.g., ``"JavaScript"``).
        files: List of absolute file paths that were processed.
        result: The extracted signature dictionaries from ``_extract_with_regex``.
    """
    from collections import Counter

    counts = Counter(sig.get("file", "") for sig in result)

    for f in files:
        try:
            path = Path(f)
            source = path.read_text(errors="replace")
        except OSError:
            continue
        fname = path.name
        file_count = counts.get(fname, 0)
        estimator = _REGEX_ESTIMATORS.get(language_name)
        estimated = len(estimator.findall(source)) if estimator else 0

        if estimated and file_count < estimated * 0.7:
            warnings.warn(
                f"Regex fallback [{language_name}] extracted {file_count}/{estimated} "
                f"signatures from {f} — may miss complex definitions. "
                f"Install tree-sitter packages for full coverage.",
                UserWarning,
                stacklevel=2,
            )
        else:
            _log.info(
                "Regex fallback [%s] extracted %d/%d signatures from %s",
                language_name, file_count, estimated or "?", f,
            )


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


def dedupe_signatures_by_fqname(
    signatures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate signature dicts by ``fqname`` and return sorted output."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for sig in signatures:
        fqname = sig["fqname"]
        if fqname not in seen:
            seen.add(fqname)
            unique.append(sig)

    unique.sort(key=lambda x: x["fqname"])
    return unique


def split_pipe_union_members(type_str: str) -> frozenset[str]:
    """Split ``A | B`` style unions, or return a singleton member set."""
    s = type_str.strip()
    if "|" in s:
        return frozenset(p.strip() for p in s.split("|"))
    return frozenset({s})


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


def _resolve_call_name_from_node(
    node: Any,
    source: bytes,
    *,
    name_on_call: bool,
    fallback_ident: bool,
    member_map: dict[str, str | None] | None,
    ident_type: str | None,
    first_ident: Callable[[Any], str | None],
) -> str | None:
    """Resolve a call target name from a tree-sitter call node."""
    if name_on_call:
        for field in ("name", "method"):
            child = node.child_by_field_name(field)
            if child is not None:
                return node_text(child, source)
        if fallback_ident:
            return first_ident(node)
        return None

    func_node = node.child_by_field_name("function")
    if func_node is None and node.named_children:
        func_node = node.named_children[0]
    if func_node is None:
        return None
    return _extract_call_name(func_node, source, member_map, ident_type)


def _resolve_args_node(node: Any, args_type: str) -> Any:
    """Resolve the argument-list node for a call expression."""
    args_node = node.child_by_field_name("arguments")
    if args_node is not None:
        return args_node
    for child in node.named_children:
        if child.type == args_type:
            return child
    if node.named_children:
        return node.named_children[-1]
    return None


def _count_call_args(
    node: Any,
    *,
    count_args: str,
    count_types: set[str] | None,
    args_type: str,
) -> int:
    """Count arguments for a call expression according to the configured mode."""
    if count_args == "arithmetic":
        return max(0, len(node.named_children) - 1)

    args_node = _resolve_args_node(node, args_type)
    if args_node is None:
        return 0

    if count_args == "include":
        types = count_types or set()
        if types:
            return sum(1 for child in args_node.children if child.type in types)

    return sum(1 for child in args_node.named_children if child.type != ",")


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
            name = _resolve_call_name_from_node(
                node,
                source,
                name_on_call=name_on_call,
                fallback_ident=fallback_ident,
                member_map=member_map,
                ident_type=ident_type,
                first_ident=_first_ident,
            )
            if name is not None:
                arg_count = _count_call_args(
                    node,
                    count_args=count_args,
                    count_types=count_types,
                    args_type=args_type,
                )
                lineno = node.start_point[0] + 1
                calls.append(make_call_dict(name, lineno, arg_count, str(path)))

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return calls
