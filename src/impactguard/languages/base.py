"""Language extractor protocol for ImpactGuard.

Defines the interface that every language extractor must implement.
New languages are added by creating a class that satisfies this Protocol
and registering it with the language registry.
"""

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LanguageExtractor(Protocol):
    """Protocol for language-specific signature and call-site extractors.

    Implement this protocol for each supported language.  Instances are
    registered via :func:`languages.registry.register` so the rest of the
    pipeline can remain language-agnostic.

    The *language* and *extensions* attributes must be plain instance
    attributes (not properties) so that :func:`isinstance` / duck-typing
    checks work correctly without calling any methods.
    """

    #: Canonical lower-case language name, e.g. ``"python"`` or ``"typescript"``.
    language: str

    #: File extensions (lower-case, including dot) handled by this extractor,
    #: e.g. ``[".py"]`` or ``[".ts", ".tsx"]``.
    extensions: list[str]

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract function/method signatures from source files.

        Args:
            files: List of source file paths.
            _base_path: Optional base path used to make ``fqname`` values
                relative.  Ignored by most implementations.

        Returns:
            List of signature dicts conforming to the ImpactGuard signature
            schema (``fqname``, ``name``, ``positional``, ``kwonly``, …).
            Each dict must include at minimum the fields required by
            :func:`schema.validate_signatures`.
        """
        ...

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a single source file.

        Args:
            path: Path to the source file.

        Returns:
            List of call-site dicts.  Each dict must contain at least
            ``name`` (callee name) and ``lineno`` (1-based line number),
            and should include ``args``, ``kwargs``, ``file``,
            ``has_starargs``, and ``has_kwargs`` where applicable.
        """
        ...

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Decompose a union type annotation into its constituent member types.

        Used by the type-compatibility comparison layer to decide whether a
        type change is widening, narrowing, or incompatible.

        Args:
            type_str: Type annotation string in the language's own syntax.

        Returns:
            Frozenset of member-type strings.  For a scalar type ``"int"``
            return ``frozenset({"int"})``.
        """
        ...
