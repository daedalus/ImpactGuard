import json
import re
import sys
from typing import Any

from ._logging import get_logger

_log = get_logger(__name__)


def load(path: str) -> dict[str, dict[str, Any]]:
    """Load signatures from a JSON file.

    Also validates the payload format and emits a warning to stderr for any
    structural issues found (validation errors are non-fatal).
    """
    from .schema import validate_signatures

    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in signatures file '{path}': {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(
            f"Signatures file '{path}': expected a JSON array, got {type(data).__name__}"
        )

    valid, errors = validate_signatures(data)
    if not valid:
        for err in errors:
            _log.warning("Signatures file '%s': %s", path, err)
            print(f"Warning: signatures file '{path}': {err}", file=sys.stderr)

    result: dict[str, dict[str, Any]] = {}
    for entry in data:
        if not isinstance(entry, dict) or "fqname" not in entry:
            _log.warning("Signatures file '%s': skipping malformed entry: %r", path, entry)
            print(f"Warning: signatures file '{path}': skipping malformed entry: {entry!r}", file=sys.stderr)
            continue
        result[entry["fqname"]] = entry
    return result


def is_required(arg: dict[str, Any]) -> bool:
    """Check if a function argument has a default value."""
    return not arg["has_default"]


def _is_public(fqname: str) -> bool:
    """Return True if the function name (last segment) is public (no leading _)."""
    name_part = fqname.split(":")[-1]
    # For class methods like ClassName.method, check the method part
    leaf = name_part.split(".")[-1]
    return not leaf.startswith("_")


def _is_effectively_public(fqname: str, sig: dict[str, Any]) -> bool:
    """Return *True* when *sig* represents a symbol that counts as public API.

    The decision order is:

    1. If the module defines ``__all__`` (``exported`` is *True* or *False*):
       only symbols with ``exported == True`` are public.
    2. Otherwise fall back to the underscore-prefix heuristic.
    """
    exported = sig.get("exported")
    if exported is not None:
        # __all__ is defined in this module
        return bool(exported)
    # No __all__ — use name-prefix heuristic
    return _is_public(fqname)


def _is_ignored(fqname: str, sig: dict[str, Any], suppress_list: list[str]) -> bool:
    """Return *True* when the function should be skipped in comparison.

    A function is suppressed when:

    * Its signature was extracted with ``ignored=True`` (inline
      ``# impactguard: ignore`` comment), **or**
    * Its *fqname* (or bare *name*) appears in *suppress_list*.
    """
    if sig.get("ignored", False):
        return True
    name = sig.get("name", "")
    return fqname in suppress_list or name in suppress_list


# ── Type-compatibility helpers ────────────────────────────────────────────────


def _parse_union_members(type_str: str) -> frozenset[str]:
    """Break a type annotation string into its constituent member types.

    Handles:

    * PEP 604 ``X | Y | Z``
    * ``Optional[X]`` → ``{X, None}``
    * ``Union[X, Y]`` → ``{X, Y}``
    * Everything else → ``{type_str}``
    """
    s = type_str.strip()

    # Optional[X]  → X | None
    m = re.fullmatch(r"Optional\[(.+)\]", s)
    if m:
        inner = m.group(1).strip()
        return frozenset({inner, "None"})

    # Union[X, Y, ...]  (top-level commas only — simple split is good enough
    # for well-formed annotations without nested generics at the top level)
    m2 = re.fullmatch(r"Union\[(.+)\]", s)
    if m2:
        parts = [p.strip() for p in m2.group(1).split(",")]
        return frozenset(parts)

    # PEP 604: X | Y | Z
    if "|" in s:
        parts = [p.strip() for p in s.split("|")]
        return frozenset(parts)

    return frozenset({s})


def _type_change_kind(
    old_type: str,
    new_type: str,
    union_parser: Any = None,
) -> str | None:
    """Classify the relationship between two type annotation strings.

    Args:
        old_type: Previous type annotation string.
        new_type: New type annotation string.
        union_parser: Optional callable ``(type_str) -> frozenset[str]``
            used to decompose union types.  Defaults to the built-in
            Python-syntax parser when *None*.

    Returns:
        ``None``       – types are identical (no change).
        ``"widening"``  – new_type is a strict superset of old_type (safe for
            callers; *non-breaking*).
        ``"narrowing"`` – new_type is a strict subset of old_type (breaking).
        ``"changed"``   – types overlap or differ with no clear direction
            (treated as breaking).
    """
    if old_type == new_type:
        return None
    parse = union_parser if union_parser is not None else _parse_union_members
    old_members = parse(old_type)
    new_members = parse(new_type)
    if new_members > old_members:
        return "widening"
    if new_members < old_members:
        return "narrowing"
    return "changed"


# ── Deprecation helper ────────────────────────────────────────────────────────


def _has_deprecated_decorator(sig: dict[str, Any]) -> bool:
    """Return *True* when the signature has a ``@deprecated``-style decorator."""
    for dec in sig.get("decorators", []):
        if "deprecated" in dec.lower():
            return True
    return False


def _load_signatures(arg: str | list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Load signatures from a file path or use the provided signature list.

    Args:
        arg: Either a path to a JSON file (str) or an already-loaded
            signature list (list[dict]).

    Returns:
        Dict mapping fqname to signature dict.
    """
    if isinstance(arg, str):
        return load(arg)
    # Assume it's already a signature list
    if not isinstance(arg, list):
        raise ValueError(
            f"Expected a list of signatures, got {type(arg).__name__}"
        )
    result: dict[str, dict[str, Any]] = {}
    for entry in arg:
        if not isinstance(entry, dict) or "fqname" not in entry:
            _log.warning("In-memory signatures: skipping malformed entry: %r", entry)
            continue
        result[entry["fqname"]] = entry
    return result


def compare(  # noqa: MC0001
    old: str | list[dict[str, Any]],
    new: str | list[dict[str, Any]],
    include_private: bool | None = None,
    language: str | None = None,
    suppress: list[str] | None = None,
    hierarchy: dict[str, Any] | None = None,
    implementations: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Compare two signature snapshots.

    Args:
        old: Path to old signatures JSON file (str) OR already-loaded
            signature list (list[dict]).
        new: Path to new signatures JSON file (str) OR already-loaded
            signature list (list[dict]).
        include_private: When *False* (default from config), functions whose
            leaf name starts with ``_`` (or that are not in ``__all__`` when
            the module defines it) are excluded from comparison.  Pass *True*
            to include them.
        language: Optional language name (e.g. ``"typescript"``) used to
            select a language-specific union-type parser for the
            type-compatibility comparison.  When *None* the built-in Python
            parser is used (backward-compatible default).

    Returns:
        Dictionary with ``'breaking'``, ``'nonbreaking'``, and
        ``'suppressed'`` lists.  ``'suppressed'`` contains the fqnames of
        functions that were skipped due to an inline ignore comment or the
        config suppress list.
    """
    from .config import get as cfg_get

    if include_private is None:
        include_private = bool(cfg_get("analysis", "include_private", False))

    suppress_list: list[str] = list(cfg_get("analysis", "suppress", [])) or []
    if suppress:
        suppress_list.extend(suppress)

    # Resolve language-specific union parser (falls back to None → Python default)
    _union_parser: Any = None
    if language is not None:
        from .languages.lib.registry import get_extractor_by_language

        _lang_ext = get_extractor_by_language(language)
        if _lang_ext is not None:
            _union_parser = _lang_ext.parse_union_members

    old_sigs: dict[str, dict[str, Any]] = _load_signatures(old)
    new_sigs: dict[str, dict[str, Any]] = _load_signatures(new)

    _log.debug(
        "Comparing signatures: %d old, %d new",
        len(old_sigs),
        len(new_sigs),
    )

    # Filter private symbols unless explicitly included
    if not include_private:
        old_sigs = {k: v for k, v in old_sigs.items() if _is_effectively_public(k, v)}
        new_sigs = {k: v for k, v in new_sigs.items() if _is_effectively_public(k, v)}

    breaking: list[str] = []
    nonbreaking: list[str] = []
    suppressed: list[str] = []

    def _suppressed(k: str, sig: dict[str, Any]) -> bool:
        if _is_ignored(k, sig, suppress_list):
            suppressed.append(k)
            return True
        return False

    # Removed functions
    for k in old_sigs:
        if k not in new_sigs:
            if _suppressed(k, old_sigs[k]):
                continue
            # Deprecation lifecycle: removing a @deprecated function is non-breaking
            if _has_deprecated_decorator(old_sigs[k]):
                nonbreaking.append(f"DEPRECATED_REMOVED: {k}")
            else:
                breaking.append(f"REMOVED: {k}")

    # Added functions
    for k in new_sigs:
        if k not in old_sigs:
            if _suppressed(k, new_sigs[k]):
                continue
            nonbreaking.append(f"ADDED: {k}")

    # Compare shared
    for k in old_sigs:
        if k not in new_sigs:
            continue
        if _suppressed(k, old_sigs[k]):
            continue

        o = old_sigs[k]
        n = new_sigs[k]

        o_pos = o["positional"]
        n_pos = n["positional"]

        # positional argument removal
        if len(n_pos) < len(o_pos):
            breaking.append(f"POSITIONAL_REMOVED: {k}")
        else:
            # positional arg changes
            for i in range(len(o_pos)):
                if o_pos[i]["name"] != n_pos[i]["name"]:
                    breaking.append(f"POSITIONAL_REORDER/RENAME: {k}")
                    break

            # new positional args
            if len(n_pos) > len(o_pos):
                added = n_pos[len(o_pos) :]
                if any(is_required(a) for a in added):
                    breaking.append(f"REQUIRED_POSITIONAL_ADDED: {k}")
                else:
                    nonbreaking.append(f"OPTIONAL_POSITIONAL_ADDED: {k}")

        # kwonly args
        o_kw = {a["name"]: a for a in o["kwonly"]}
        n_kw = {a["name"]: a for a in n["kwonly"]}

        for name in o_kw:
            if name not in n_kw:
                breaking.append(f"KWONLY_REMOVED: {k}")

        for name in n_kw:
            if name not in o_kw:
                if is_required(n_kw[name]):
                    breaking.append(f"REQUIRED_KWONLY_ADDED: {k}")
                else:
                    nonbreaking.append(f"OPTIONAL_KWONLY_ADDED: {k}")

        # varargs changes
        if o["vararg"] and not n["vararg"]:
            breaking.append(f"*args_REMOVED: {k}")

        if o["kwarg"] and not n["kwarg"]:
            breaking.append(f"**kwargs_REMOVED: {k}")

        # ── Type annotation changes ────────────────────────────────────────

        # Per-argument type changes
        for o_arg, n_arg in zip(o_pos, n_pos):
            o_type = o_arg.get("type")
            n_type = n_arg.get("type")
            if o_type is not None and n_type is not None and o_type != n_type:
                kind = _type_change_kind(o_type, n_type, _union_parser)
                if kind == "widening":
                    nonbreaking.append(
                        f"TYPE_WIDENED: {k} arg '{o_arg['name']}' {o_type} -> {n_type}"
                    )
                else:
                    breaking.append(
                        f"TYPE_CHANGED: {k} arg '{o_arg['name']}' {o_type} -> {n_type}"
                    )

        for o_arg_name, o_arg in o_kw.items():
            if o_arg_name in n_kw:
                o_type = o_arg.get("type")
                n_type = n_kw[o_arg_name].get("type")
                if o_type is not None and n_type is not None and o_type != n_type:
                    kind = _type_change_kind(o_type, n_type, _union_parser)
                    if kind == "widening":
                        nonbreaking.append(
                            f"TYPE_WIDENED: {k} kwarg '{o_arg_name}' {o_type} -> {n_type}"
                        )
                    else:
                        breaking.append(
                            f"TYPE_CHANGED: {k} kwarg '{o_arg_name}' {o_type} -> {n_type}"
                        )

        # Return type changes
        o_ret = o.get("return_type")
        n_ret = n.get("return_type")
        if o_ret is not None and n_ret is not None and o_ret != n_ret:
            kind = _type_change_kind(o_ret, n_ret, _union_parser)
            if kind == "widening":
                nonbreaking.append(f"RETURN_TYPE_WIDENED: {k} {o_ret} -> {n_ret}")
            else:
                breaking.append(f"RETURN_TYPE_CHANGED: {k} {o_ret} -> {n_ret}")

        # ── Decorator changes ──────────────────────────────────────────────
        o_decs = set(o.get("decorators", []))
        n_decs = set(n.get("decorators", []))
        for removed_dec in o_decs - n_decs:
            breaking.append(f"DECORATOR_REMOVED: {k} @{removed_dec}")
        for added_dec in n_decs - o_decs:
            # Adding a decorator is typically non-breaking (e.g. @lru_cache, @staticmethod)
            # Only decorators like @classmethod that change calling convention are breaking
            nonbreaking.append(f"DECORATOR_ADDED: {k} @{added_dec}")

    # ── Cascade impact from class hierarchy ──────────────────────────────
    if hierarchy:
        from .class_hierarchy import get_cascade_changes

        cascade = get_cascade_changes(
            {"breaking": breaking, "nonbreaking": nonbreaking},
            hierarchy,
            implementations,
        )
        breaking.extend(cascade)

    breaking_sorted = sorted(set(breaking))
    nonbreaking_sorted = sorted(set(nonbreaking))
    suppressed_sorted = sorted(set(suppressed))

    _log.debug(
        "Comparison result: %d breaking, %d non-breaking, %d suppressed",
        len(breaking_sorted),
        len(nonbreaking_sorted),
        len(suppressed_sorted),
    )
    return {
        "breaking": breaking_sorted,
        "nonbreaking": nonbreaking_sorted,
        "suppressed": suppressed_sorted,
    }
