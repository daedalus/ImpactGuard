"""Language extractor registry for ImpactGuard.

Maps file extensions and language names to :class:`LanguageExtractor`
instances.  Language modules register themselves by calling
:func:`register` at import time.

Third-party packages can contribute additional extractors by declaring an
entry point in the ``impactguard.languages`` group in their
``pyproject.toml``::

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

import functools
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .lib.base import LanguageExtractor

# Extension (lower-case, with leading dot) → extractor instance
_BY_EXTENSION: dict[str, LanguageExtractor] = {}

# Language name (lower-case) → extractor instance
_BY_LANGUAGE: dict[str, LanguageExtractor] = {}

_T = TypeVar("_T")

# Tracks whether third-party entry-point plugins have been loaded yet.
_PLUGINS_LOADED: bool = False


def _auto_populate(fn: Callable[..., _T]) -> Callable[..., _T]:
    """Decorator: ensure built-in extractors are registered before calling *fn*."""

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> _T:
        if not _BY_LANGUAGE:
            # Import triggers self-registration at module level
            from .. import c as _c_mod  # noqa: F401
            from .. import csharp as _csharp_mod  # noqa: F401
            from .. import go as _go_mod  # noqa: F401
            from .. import haskell as _haskell_mod  # noqa: F401
            from .. import java as _java_mod  # noqa: F401
            from .. import javascript as _js_mod  # noqa: F401
            from .. import kotlin as _kotlin_mod  # noqa: F401
            from .. import python as _py_mod  # noqa: F401
            from .. import ruby as _ruby_mod  # noqa: F401
            from .. import rust as _rust_mod  # noqa: F401
            from .. import swift as _swift_mod  # noqa: F401
            from .. import typescript as _ts_mod  # noqa: F401
            from .. import zig as _zig_mod  # noqa: F401
        _load_plugins()
        return fn(*args, **kwargs)

    return wrapper


def _load_plugins() -> None:
    """Discover and register third-party language extractors via entry points.

    Scans the ``impactguard.languages`` entry-point group for any installed
    packages that register additional extractors.  Each entry point must
    resolve to a class (not an instance) that satisfies the
    :class:`~base.LanguageExtractor` protocol.  The class is instantiated
    with no arguments.

    This function is idempotent — it only runs once per interpreter session.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True

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


@_auto_populate
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


@_auto_populate
def get_extractor_by_language(language: str) -> LanguageExtractor | None:
    """Return the extractor for a named language.

    Args:
        language: Canonical language name (case-insensitive), e.g.
            ``"python"`` or ``"typescript"``.

    Returns:
        The registered :class:`~base.LanguageExtractor`, or *None*.
    """
    return _BY_LANGUAGE.get(language.lower())


@_auto_populate
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


@_auto_populate
def list_languages() -> list[str]:
    """Return sorted names of all registered languages."""
    return sorted(_BY_LANGUAGE.keys())


@_auto_populate
def list_extensions() -> list[str]:
    """Return sorted list of all registered file extensions."""
    return sorted(_BY_EXTENSION.keys())
