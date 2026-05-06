"""Python language extractor for ImpactGuard.

Wraps the existing :mod:`extract_signatures` and :mod:`extract_calls`
modules so that Python participates in the language-agnostic registry.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..extract_calls import extract as _extract_calls_impl
from ..extract_signatures import extract as _extract_sigs_impl


class PythonExtractor:
    """Language extractor for Python source files.

    Delegates to the pre-existing :func:`extract_signatures.extract` and
    :func:`extract_calls.extract` implementations so that all existing
    behaviour is preserved unchanged.
    """

    language: str = "python"
    extensions: list[str] = [".py"]

    # ── LanguageExtractor protocol ────────────────────────────────────────────

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from Python files.

        Delegates to :func:`extract_signatures.extract`.
        """
        return _extract_sigs_impl(files, _base_path=_base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a single Python file.

        Delegates to :func:`extract_calls.extract`.
        """
        return _extract_calls_impl(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse Python union type syntax into member types.

        Handles:

        * ``Optional[X]`` → ``{X, "None"}``
        * ``Union[X, Y, …]`` → ``{X, Y, …}``
        * ``X | Y`` (PEP 604) → ``{X, Y}``
        * Everything else → ``{type_str}``
        """
        s = type_str.strip()

        m = re.fullmatch(r"Optional\[(.+)\]", s)
        if m:
            return frozenset({m.group(1).strip(), "None"})

        m2 = re.fullmatch(r"Union\[(.+)\]", s)
        if m2:
            return frozenset(p.strip() for p in m2.group(1).split(","))

        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))

        return frozenset({s})


# ── Self-registration ─────────────────────────────────────────────────────────


def _register() -> None:
    from .registry import register

    register(PythonExtractor())


_register()
