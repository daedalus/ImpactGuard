"""Shared library modules for language extractors."""

from .base import LanguageExtractor
from .registry import (
    get_extractor,
    get_extractor_by_language,
    list_extensions,
    register,
)
from .shared import (
    call_re,
    child_of_type,
    extract_calls_with_tree_sitter,
    has_ignore_comment,
    has_ignore_comment_fallback,
    make_call_dict,
    make_signature_dict,
    node_text,
    register_extractor,
    warn_if_no_tree_sitter,
)

__all__ = [
    "LanguageExtractor",
    "register",
    "get_extractor",
    "get_extractor_by_language",
    "list_extensions",
    "call_re",
    "child_of_type",
    "extract_calls_with_tree_sitter",
    "has_ignore_comment",
    "has_ignore_comment_fallback",
    "make_call_dict",
    "make_signature_dict",
    "node_text",
    "register_extractor",
    "warn_if_no_tree_sitter",
]
