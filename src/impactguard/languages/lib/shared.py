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
