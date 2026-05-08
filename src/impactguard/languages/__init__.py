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

# Import built-in language modules to trigger self-registration with the registry.
# This keeps the registry (languages.lib.registry) unaware of top-level language
# modules; they register themselves when imported.
from . import c as _c_mod  # noqa: F401
from . import csharp as _csharp_mod  # noqa: F401
from . import go as _go_mod  # noqa: F401
from . import haskell as _haskell_mod  # noqa: F401
from . import java as _java_mod  # noqa: F401
from . import javascript as _js_mod  # noqa: F401
from . import kotlin as _kotlin_mod  # noqa: F401
from . import python as _py_mod  # noqa: F401
from . import ruby as _ruby_mod  # noqa: F401
from . import rust as _rust_mod  # noqa: F401
from . import swift as _swift_mod  # noqa: F401
from . import typescript as _ts_mod  # noqa: F401
from . import zig as _zig_mod  # noqa: F401
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
