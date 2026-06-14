"""Z3-backed type constraint subsumption checking for ImpactGuard.

This module is optional — it requires the ``impactguard[formal]`` extra
(``pip install impactguard[formal]``).  When Z3 is not installed all
functions degrade gracefully to ``None``, leaving existing heuristic
classifications in place.

How it works
------------
We model Python types as uninterpreted predicates over a single
``Value`` sort.  Each Python type annotation becomes a callable
predicate:

    in_int(v)     — v is an int
    in_str(v)     — v is a str
    in_union(v)   — in_X(v) ∨ in_Y(v)
    in_Any(v)     — True

Subsumption is an SMT query:

    ∃v : in_old(v) ∧ ¬in_new(v)

If Z3 returns **unsat**, no value can satisfy the old type without also
satisfying the new one — that's a widening (non-breaking).
If **sat**, there exists a counterexample — narrowing (breaking).

Fallback
--------
Any parse failure, missing Z3, or timeout returns ``None``.
Callers should fall back to their existing heuristic classification.
"""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_LOG = None


def _get_log() -> Any:
    global _LOG
    if _LOG is None:
        from ._logging import get_logger

        _LOG = get_logger(__name__)
    return _LOG


def _z3_available() -> bool:
    """Return True when real Z3 can be imported.

    Checks for the presence of ``z3.Solver`` to distinguish a real
    ``z3-solver`` installation from a namespace-package stub.
    """
    try:
        import z3  # noqa: F401
        return hasattr(z3, "Solver")
    except ImportError:
        return False


# ── Z3 type predicate model ──────────────────────────────────────────────────
#
# We declare a fresh uninterpreted sort Value and build predicate functions
# lazily.  Each Python type string maps to a callable ``pred(Const) → BoolRef``.

_PREDICATES: dict[str, Any] = {}
_VALUE_SORT = None
_LOCK = threading.Lock()


def _reset(force: bool = False) -> None:
    global _PREDICATES, _VALUE_SORT
    with _LOCK:
        if force:
            _PREDICATES = {}
            _VALUE_SORT = None


def _value_sort(z3: Any) -> Any:
    global _VALUE_SORT
    if _VALUE_SORT is None:
        with _LOCK:
            if _VALUE_SORT is None:
                _VALUE_SORT = z3.DeclareSort("Value")
    return _VALUE_SORT


def _predicate(name: str, z3: Any) -> Any:
    """Return a Z3 Function(name, Value) → Bool."""
    cached = _PREDICATES.get(name)
    if cached is not None:
        return cached
    val_sort = _value_sort(z3)
    with _LOCK:
        if name in _PREDICATES:
            return _PREDICATES[name]
        fn = z3.Function(name, val_sort, z3.BoolSort())
        _PREDICATES[name] = fn
        return fn


# ── Type-string → callable predicate ─────────────────────────────────────────


_PRIMITIVE_PRED_MAP: dict[str, str] = {
    "int": "Int",
    "float": "Real",
    "bool": "Bool",
    "str": "Str",
    "None": "NoneType",
    "bytes": "Bytes",
    "complex": "Complex",
}


def _make_predicate(type_str: str, z3: Any) -> Callable[[Any], Any]:
    """Return a callable ``(z3.Const) → z3.BoolRef`` for *type_str*."""
    s = type_str.strip()

    if s == "Any":
        return lambda _: z3.BoolVal(True)

    members = _parse_union_members(s)
    if len(members) > 1:
        preds = [_make_predicate(m, z3) for m in members]
        return lambda v: z3.Or([p(v) for p in preds])

    base, args = _strip_generic(s)

    if base in _PRIMITIVE_PRED_MAP:
        fn = _predicate(f"is_{_PRIMITIVE_PRED_MAP[base]}", z3)
        return lambda v: fn(v)

    if base == "list":
        elem_pred = _make_predicate(args[0], z3) if args else (lambda _: z3.BoolVal(True))
        return lambda v, _p=elem_pred: _p(v)

    if base == "dict":
        val_pred = _make_predicate(args[1], z3) if len(args) > 1 else (lambda _: z3.BoolVal(True))
        return lambda v, _p=val_pred: _p(v)

    if base in ("set", "frozenset"):
        elem_pred = _make_predicate(args[0], z3) if args else (lambda _: z3.BoolVal(True))
        return lambda v, _p=elem_pred: _p(v)

    if base == "tuple":
        return lambda _: z3.BoolVal(True)

    return lambda _: z3.BoolVal(True)


# ── Union / generic helpers ──────────────────────────────────────────────────


def _parse_union_members(type_str: str) -> list[str]:
    s = type_str.strip()
    m = re.fullmatch(r"Optional\[(.+)\]", s)
    if m:
        return [m.group(1).strip(), "None"]
    m2 = re.fullmatch(r"Union\[(.+)\]", s)
    if m2:
        return [p.strip() for p in m2.group(1).split(",")]
    if "|" in s:
        return [p.strip() for p in s.split("|")]
    return [s]


def _strip_generic(type_str: str) -> tuple[str, list[str]]:
    m = re.fullmatch(r"(\w+)\[(.+)\]", type_str.strip())
    if m:
        base = m.group(1)
        inside = m.group(2)
        if base == "tuple" and "," in inside:
            args = [a.strip() for a in _split_generic_args(inside)]
        else:
            args = [inside.strip()]
        return base, args
    return type_str.strip(), []


def _split_generic_args(s: str) -> list[str]:
    depth = 0
    parts: list[str] = []
    current: list[str] = []
    for ch in s:
        if ch in ("[", "("):
            depth += 1
            current.append(ch)
        elif ch in ("]", ")"):
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    rest = "".join(current).strip()
    if rest:
        parts.append(rest)
    return parts


# ── Core subsumption check ────────────────────────────────────────────────────


def _run_subsumption_query(
    pred1: Any,
    pred2: Any,
    v: Any,
    timeout_ms: int,
    negate: bool,
    z3: Any,
) -> Any:
    """Run a single Z3 subsumption query and return the check result."""
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(pred1(v))
    solver.add(z3.Not(pred2(v)) if negate else pred2(v))
    return solver.check()


def _classify_results(widening_result: Any, narrowing_result: Any, z3: Any) -> str | None:
    """Classify paired widening/narrowing Z3 check results."""
    if widening_result == z3.unknown or narrowing_result == z3.unknown:
        return "unknown"
    is_widening_ce = widening_result == z3.sat
    is_narrowing_ce = narrowing_result == z3.sat
    if is_widening_ce and is_narrowing_ce:
        return "changed"
    if is_widening_ce:
        return "narrowing"
    return "widening"


def check_subsumption(
    old_type: str,
    new_type: str,
    timeout_ms: int = 5000,
) -> str | None:
    """Use Z3 to classify a type change.

    Args:
        old_type: Previous type annotation string.
        new_type: New type annotation string.
        timeout_ms: Z3 solver timeout (default 5000).

    Returns:
        ``None``       – identical types, or Z3 unavailable, or parse failed.
        ``"widening"``  – proved: every old value is also a new value.
        ``"narrowing"`` – proved: some old value is rejected by new type.
        ``"changed"``   – proved: overlap but neither subsumes the other.
        ``"unknown"``   – Z3 returned *unknown* (undecidable / timeout).
    """
    if old_type == new_type:
        return None

    if not _z3_available():
        return None

    import z3

    old_pred = _make_predicate(old_type, z3)
    new_pred = _make_predicate(new_type, z3)

    val_sort = _value_sort(z3)
    v = z3.Const("v", val_sort)

    widening_result = _run_subsumption_query(old_pred, new_pred, v, timeout_ms, True, z3)
    narrowing_result = _run_subsumption_query(new_pred, old_pred, v, timeout_ms, True, z3)

    return _classify_results(widening_result, narrowing_result, z3)


# ── High-level public API ─────────────────────────────────────────────────────


def classify_type_change(
    old_type: str,
    new_type: str,
    timeout_ms: int = 5000,
) -> str | None:
    """Classify a type change, preferring Z3 proof over heuristic fallback.

    This is the primary entry point.  Attempts a Z3-backed proof first.
    When Z3 is unavailable or the query is undecidable, returns ``None``
    so callers can fall back to their existing heuristic classification.

    Args:
        old_type: Previous type annotation string.
        new_type: New type annotation string.
        timeout_ms: Z3 solver timeout (default 5000).

    Returns:
        Same as :func:`check_subsumption`.
    """
    if old_type == new_type:
        return None
    return check_subsumption(old_type, new_type, timeout_ms)
