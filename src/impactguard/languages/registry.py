"""Language extractor registry for ImpactGuard.

Maps file extensions and language names to :class:`LanguageExtractor`
instances.  Language modules register themselves by calling
:func:`register` at import time.

Usage::

    from impactguard.languages.registry import get_extractor, detect_language

    extractor = get_extractor("myfile.ts")
    if extractor:
        sigs = extractor.extract_signatures(["myfile.ts"])
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LanguageExtractor

# Extension (lower-case, with leading dot) → extractor instance
_BY_EXTENSION: dict[str, LanguageExtractor] = {}

# Language name (lower-case) → extractor instance
_BY_LANGUAGE: dict[str, LanguageExtractor] = {}


def register(extractor: LanguageExtractor) -> None:
    """Register a language extractor.

    All extensions listed in ``extractor.extensions`` are mapped to the
    extractor, and ``extractor.language`` is mapped to the same instance.
    Registering a second extractor for the same extension/language silently
    replaces the previous one.

    Args:
        extractor: An object satisfying the :class:`~base.LanguageExtractor`
            protocol.
    """
    _BY_LANGUAGE[extractor.language.lower()] = extractor
    for ext in extractor.extensions:
        _BY_EXTENSION[ext.lower()] = extractor


def get_extractor(file: str) -> LanguageExtractor | None:
    """Return the extractor for *file* based on its extension.

    Args:
        file: File path or just a file name; only the extension is examined.

    Returns:
        The registered :class:`~base.LanguageExtractor` for the file's
        extension, or *None* if no extractor has been registered for that
        extension.
    """
    ext = Path(file).suffix.lower()
    return _BY_EXTENSION.get(ext)


def get_extractor_by_language(language: str) -> LanguageExtractor | None:
    """Return the extractor for a named language.

    Args:
        language: Canonical language name (case-insensitive), e.g.
            ``"python"`` or ``"typescript"``.

    Returns:
        The registered :class:`~base.LanguageExtractor`, or *None*.
    """
    return _BY_LANGUAGE.get(language.lower())


def detect_language(file: str) -> str | None:
    """Return the language name for *file*, or *None* if unknown.

    Args:
        file: File path or file name.

    Returns:
        Lower-case language name string, or *None* when no extractor is
        registered for the file's extension.
    """
    ext = Path(file).suffix.lower()
    extractor = _BY_EXTENSION.get(ext)
    return extractor.language if extractor else None


def list_languages() -> list[str]:
    """Return sorted names of all registered languages."""
    return sorted(_BY_LANGUAGE.keys())


def list_extensions() -> list[str]:
    """Return sorted list of all registered file extensions."""
    return sorted(_BY_EXTENSION.keys())


def _ensure_defaults_registered() -> None:
    """Import and register the built-in language extractors if not yet done.

    Called lazily by :func:`get_extractor` and :func:`get_extractor_by_language`
    so that the registry is always populated when needed without requiring
    callers to manage imports.
    """
    if not _BY_LANGUAGE:
        # Import triggers self-registration at module level
        from . import python as _py_mod  # noqa: F401
        from . import typescript as _ts_mod  # noqa: F401


# Patch the public lookup functions to auto-populate on first call.

_orig_get_extractor = get_extractor
_orig_get_extractor_by_language = get_extractor_by_language
_orig_detect_language = detect_language
_orig_list_languages = list_languages
_orig_list_extensions = list_extensions


def get_extractor(file: str) -> LanguageExtractor | None:  # type: ignore[no-redef]
    _ensure_defaults_registered()
    return _orig_get_extractor(file)


def get_extractor_by_language(language: str) -> LanguageExtractor | None:  # type: ignore[no-redef]
    _ensure_defaults_registered()
    return _orig_get_extractor_by_language(language)


def detect_language(file: str) -> str | None:  # type: ignore[no-redef]
    _ensure_defaults_registered()
    return _orig_detect_language(file)


def list_languages() -> list[str]:  # type: ignore[no-redef]
    _ensure_defaults_registered()
    return _orig_list_languages()


def list_extensions() -> list[str]:  # type: ignore[no-redef]
    _ensure_defaults_registered()
    return _orig_list_extensions()
