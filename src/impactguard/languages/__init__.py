"""Language support subpackage for ImpactGuard.

Provides a language-agnostic interface for extracting function signatures
and call sites from source files in multiple programming languages.

Quickstart::

    from impactguard.languages import get_extractor, detect_language

    # Auto-detect language from file extension
    extractor = get_extractor("api.ts")
    if extractor:
        sigs = extractor.extract_signatures(["api.ts"])

    # Explicit language lookup
    from impactguard.languages import get_extractor_by_language
    py = get_extractor_by_language("python")

Supported languages (built-in):

* **python** — ``.py`` files, via the existing ``ast``-based extractors.
* **typescript** — ``.ts`` / ``.tsx`` files, via tree-sitter (preferred) or
  a regex fallback.

New languages can be added by:

1. Creating a module inside ``impactguard.languages`` that defines a class
   satisfying the :class:`~base.LanguageExtractor` protocol.
2. Calling :func:`~registry.register` with an instance of that class.
"""

from .lib.base import LanguageExtractor
from .lib.registry import (
    detect_language,
    get_extractor,
    get_extractor_by_language,
    list_extensions,
    list_languages,
    register,
)

__all__ = [
    "LanguageExtractor",
    "register",
    "get_extractor",
    "get_extractor_by_language",
    "detect_language",
    "list_languages",
    "list_extensions",
]
