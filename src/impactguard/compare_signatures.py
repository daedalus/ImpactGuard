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
            _log.warning(
                "Signatures file '%s': skipping malformed entry: %r", path, entry
            )
            print(
                f"Warning: signatures file '{path}': skipping malformed entry: {entry!r}",
                file=sys.stderr,
            )
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

    # ── Attempt Z3-backed proof (requires impactguard[formal]) ──────────
    try:
        from .constraint_check import classify_type_change

        z3_result = classify_type_change(old_type, new_type)
        if z3_result is not None and z3_result != "unknown":
            return z3_result
    except ImportError:
        pass

    # ── Heuristic fallback (set-based union parsing) ────────────────────
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
        raise ValueError(f"Expected a list of signatures, got {type(arg).__name__}")
    result: dict[str, dict[str, Any]] = {}
    for entry in arg:
        if not isinstance(entry, dict) or "fqname" not in entry:
            _log.warning("In-memory signatures: skipping malformed entry: %r", entry)
            continue
        result[entry["fqname"]] = entry
    return result


def _resolve_union_parser(language: str | None) -> Any:
    """Resolve the union parser for the requested language, if any."""
    if language is None:
        return None

    from .languages.lib.registry import get_extractor_by_language

    extractor = get_extractor_by_language(language)
    if extractor is None:
        return None
    return extractor.parse_union_members


def _filter_effective_public(
    signatures: dict[str, dict[str, Any]], include_private: bool
) -> dict[str, dict[str, Any]]:
    """Filter out private signatures unless explicitly requested."""
    if include_private:
        return signatures
    return {k: v for k, v in signatures.items() if _is_effectively_public(k, v)}


def _collect_added_removed_changes(
    old_sigs: dict[str, dict[str, Any]],
    new_sigs: dict[str, dict[str, Any]],
    is_suppressed: Any,
    breaking: list[str],
    nonbreaking: list[str],
) -> None:
    """Collect added and removed symbol changes."""
    for fqname, old_sig in old_sigs.items():
        if fqname in new_sigs:
            continue
        if is_suppressed(fqname, old_sig):
            continue
        if _has_deprecated_decorator(old_sig):
            nonbreaking.append(f"DEPRECATED_REMOVED: {fqname}")
        else:
            breaking.append(f"REMOVED: {fqname}")

    for fqname, new_sig in new_sigs.items():
        if fqname in old_sigs or is_suppressed(fqname, new_sig):
            continue
        nonbreaking.append(f"ADDED: {fqname}")


def _compare_positional_args(
    fqname: str,
    old_sig: dict[str, Any],
    new_sig: dict[str, Any],
    breaking: list[str],
    nonbreaking: list[str],
) -> None:
    """Compare positional argument compatibility."""
    old_pos = old_sig["positional"]
    new_pos = new_sig["positional"]
    if len(new_pos) < len(old_pos):
        breaking.append(f"POSITIONAL_REMOVED: {fqname}")

    for old_arg, new_arg in zip(old_pos, new_pos):
        if old_arg["name"] != new_arg["name"]:
            breaking.append(f"POSITIONAL_REORDER/RENAME: {fqname}")
            break

    if len(new_pos) <= len(old_pos):
        return

    added = new_pos[len(old_pos) :]
    if any(is_required(arg) for arg in added):
        breaking.append(f"REQUIRED_POSITIONAL_ADDED: {fqname}")
    else:
        nonbreaking.append(f"OPTIONAL_POSITIONAL_ADDED: {fqname}")


def _compare_kwonly_args(
    fqname: str,
    old_sig: dict[str, Any],
    new_sig: dict[str, Any],
    breaking: list[str],
    nonbreaking: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compare keyword-only arguments and return their lookup tables."""
    old_kw = {arg["name"]: arg for arg in old_sig["kwonly"]}
    new_kw = {arg["name"]: arg for arg in new_sig["kwonly"]}

    for name in old_kw:
        if name not in new_kw:
            breaking.append(f"KWONLY_REMOVED: {fqname} '{name}'")

    for name, new_arg in new_kw.items():
        if name in old_kw:
            continue
        if is_required(new_arg):
            breaking.append(f"REQUIRED_KWONLY_ADDED: {fqname}")
        else:
            nonbreaking.append(f"OPTIONAL_KWONLY_ADDED: {fqname}")

    return old_kw, new_kw


def _compare_varargs(
    fqname: str,
    old_sig: dict[str, Any],
    new_sig: dict[str, Any],
    breaking: list[str],
) -> None:
    """Compare varargs and kwargs compatibility."""
    if old_sig["vararg"] and not new_sig["vararg"]:
        breaking.append(f"*args_REMOVED: {fqname}")
    if old_sig["kwarg"] and not new_sig["kwarg"]:
        breaking.append(f"**kwargs_REMOVED: {fqname}")


def _append_type_change(
    kind: str | None,
    widened_msg: str,
    changed_msg: str,
    breaking: list[str],
    nonbreaking: list[str],
) -> None:
    """Append the appropriate message for a detected type change."""
    if kind == "widening":
        nonbreaking.append(widened_msg)
    elif kind is not None:
        breaking.append(changed_msg)


def _compare_argument_types(
    fqname: str,
    old_sig: dict[str, Any],
    new_sig: dict[str, Any],
    old_kw: dict[str, Any],
    new_kw: dict[str, Any],
    union_parser: Any,
    breaking: list[str],
    nonbreaking: list[str],
) -> None:
    """Compare positional and kw-only argument type annotations."""
    for old_arg, new_arg in zip(old_sig["positional"], new_sig["positional"]):
        old_type = old_arg.get("type")
        new_type = new_arg.get("type")
        if old_type is None or new_type is None or old_type == new_type:
            continue
        kind = _type_change_kind(old_type, new_type, union_parser)
        _append_type_change(
            kind,
            f"TYPE_WIDENED: {fqname} arg '{old_arg['name']}' {old_type} -> {new_type}",
            f"TYPE_CHANGED: {fqname} arg '{old_arg['name']}' {old_type} -> {new_type}",
            breaking,
            nonbreaking,
        )

    for arg_name, old_arg in old_kw.items():
        if arg_name not in new_kw:
            continue
        old_type = old_arg.get("type")
        new_type = new_kw[arg_name].get("type")
        if old_type is None or new_type is None or old_type == new_type:
            continue
        kind = _type_change_kind(old_type, new_type, union_parser)
        _append_type_change(
            kind,
            f"TYPE_WIDENED: {fqname} kwarg '{arg_name}' {old_type} -> {new_type}",
            f"TYPE_CHANGED: {fqname} kwarg '{arg_name}' {old_type} -> {new_type}",
            breaking,
            nonbreaking,
        )


def _compare_return_type(
    fqname: str,
    old_sig: dict[str, Any],
    new_sig: dict[str, Any],
    union_parser: Any,
    breaking: list[str],
    nonbreaking: list[str],
) -> None:
    """Compare return type compatibility."""
    old_ret = old_sig.get("return_type")
    new_ret = new_sig.get("return_type")
    if old_ret is None or new_ret is None or old_ret == new_ret:
        return
    kind = _type_change_kind(old_ret, new_ret, union_parser)
    _append_type_change(
        kind,
        f"RETURN_TYPE_WIDENED: {fqname} {old_ret} -> {new_ret}",
        f"RETURN_TYPE_CHANGED: {fqname} {old_ret} -> {new_ret}",
        breaking,
        nonbreaking,
    )


def _compare_decorators(
    fqname: str,
    old_sig: dict[str, Any],
    new_sig: dict[str, Any],
    breaking: list[str],
    nonbreaking: list[str],
) -> None:
    """Compare decorator lists between two signatures."""
    old_decorators = set(old_sig.get("decorators", []))
    new_decorators = set(new_sig.get("decorators", []))
    for decorator in old_decorators - new_decorators:
        breaking.append(f"DECORATOR_REMOVED: {fqname} @{decorator}")
    for decorator in new_decorators - old_decorators:
        nonbreaking.append(f"DECORATOR_ADDED: {fqname} @{decorator}")


def _compare_shared_signatures(
    old_sigs: dict[str, dict[str, Any]],
    new_sigs: dict[str, dict[str, Any]],
    is_suppressed: Any,
    union_parser: Any,
    breaking: list[str],
    nonbreaking: list[str],
) -> None:
    """Compare signatures that exist in both snapshots."""
    for fqname, old_sig in old_sigs.items():
        if fqname not in new_sigs or is_suppressed(fqname, old_sig):
            continue

        new_sig = new_sigs[fqname]
        _compare_positional_args(fqname, old_sig, new_sig, breaking, nonbreaking)
        old_kw, new_kw = _compare_kwonly_args(
            fqname, old_sig, new_sig, breaking, nonbreaking
        )
        _compare_varargs(fqname, old_sig, new_sig, breaking)
        _compare_argument_types(
            fqname,
            old_sig,
            new_sig,
            old_kw,
            new_kw,
            union_parser,
            breaking,
            nonbreaking,
        )
        _compare_return_type(
            fqname, old_sig, new_sig, union_parser, breaking, nonbreaking
        )
        _compare_decorators(fqname, old_sig, new_sig, breaking, nonbreaking)


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

    union_parser = _resolve_union_parser(language)

    old_sigs: dict[str, dict[str, Any]] = _load_signatures(old)
    new_sigs: dict[str, dict[str, Any]] = _load_signatures(new)

    _log.debug(
        "Comparing signatures: %d old, %d new",
        len(old_sigs),
        len(new_sigs),
    )

    old_sigs = _filter_effective_public(old_sigs, include_private)
    new_sigs = _filter_effective_public(new_sigs, include_private)

    breaking: list[str] = []
    nonbreaking: list[str] = []
    suppressed: list[str] = []

    def _suppressed(k: str, sig: dict[str, Any]) -> bool:
        if _is_ignored(k, sig, suppress_list):
            suppressed.append(k)
            return True
        return False

    _collect_added_removed_changes(
        old_sigs, new_sigs, _suppressed, breaking, nonbreaking
    )
    _compare_shared_signatures(
        old_sigs,
        new_sigs,
        _suppressed,
        union_parser,
        breaking,
        nonbreaking,
    )

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
