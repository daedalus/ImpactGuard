"""Language extractor registry for ImpactGuard.

Maps file extensions and language names to :class:`LanguageExtractor`
instances.  Language modules register themselves by calling
:func:`register` at import time.

Third-party packages can contribute additional extractors by declaring an
entry point in the ``pyproject.toml``::

    [project.entry-points."impactguard.languages"]
    mylang = "mypkg.mylang_extractor:MyLangExtractor"

The class referenced by the entry point must satisfy the
:class:`~base.LanguageExtractor` protocol (i.e. have ``language``,
``extensions``, ``extract_signatures``, ``extract_calls``, and
``parse_union_members``).  It is instantiated with no arguments and
registered automatically the first time any registry function is called.

Usage::

    from impactguard.languages.lib.registry import get_extractor, detect_language

    extractor = get_extractor("myfile.ts")
    if extractor:
        sigs = extractor.extract_signatures(["myfile.ts"])
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .base import LanguageExtractor

# Extension (lower-case, with leading dot) → extractor instance
_BY_EXTENSION: dict[str, LanguageExtractor] = {}

# Language name (lower-case) → extractor instance
_BY_LANGUAGE: dict[str, LanguageExtractor] = {}

_T = TypeVar("_T")


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
    _ensure_loaded()
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
    _ensure_loaded()
    return _BY_LANGUAGE.get(language.lower())


def detect_language(file: str) -> str | None:
    """Return the language name for *file*, or *None* if unknown.

    Args:
        file: File path or file name.

    Returns:
        Lower-case language name string, or *None* if no extractor is
        registered for the file's extension.
    """
    _ensure_loaded()
    ext = Path(file).suffix.lower()
    extractor = _BY_EXTENSION.get(ext)
    return extractor.language if extractor else None


def list_languages() -> list[str]:
    """Return sorted names of all registered languages."""
    _ensure_loaded()
    return sorted(_BY_LANGUAGE.keys())


def list_extensions() -> list[str]:
    """Return sorted list of all registered file extensions."""
    _ensure_loaded()
    return sorted(_BY_EXTENSION.keys())


def _ensure_loaded() -> None:
    """Lazily load third-party language plugins (if not already loaded)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    _load_plugins()


_LOADED: bool = False


def _load_plugins() -> None:
    """Discover and register third-party language extractors via entry points.

    Scans the ``impactguard.languages`` entry-point group for any installed
    packages that register additional extractors.  Each entry point must
    resolve to a class (not an instance) that satisfies the
    :class:`~base.LanguageExtractor` protocol.  The class is instantiated
    with no arguments.

    This function is idempotent — it only runs once per interpreter session.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return  # Python < 3.9 — no-op

    try:
        eps = entry_points(group="impactguard.languages")
    except Exception:
        return

    for ep in eps:
        try:
            extractor_cls = ep.load()
            extractor_instance = extractor_cls()
            register(extractor_instance)
        except Exception as exc:  # pragma: no cover
            import warnings

            warnings.warn(
                f"ImpactGuard: failed to load language plugin '{ep.name}': {exc}",
                UserWarning,
                stacklevel=2,
            )
