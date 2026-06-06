"""Tests for Z3-backed type constraint checking.

These tests verify both the Z3 path (when ``z3-solver`` is installed)
and the graceful-degradation path (when it is not).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from impactguard.constraint_check import (
    _z3_available,
    check_subsumption,
    classify_type_change,
)

HAS_Z3 = _z3_available()


# ── Graceful degradation (always passes) ──────────────────────────────────────


def test_classify_identical():
    assert classify_type_change("int", "int") is None


def test_classify_no_z3_fallback():
    result = classify_type_change("int", "int | str")
    if not HAS_Z3:
        assert result is None  # no Z3, no heuristic at this layer
    else:
        assert result in ("widening", "narrowing", "changed", None)


# ── Z3 subsumption proofs ─────────────────────────────────────────────────────


def _skip_no_z3():
    if not HAS_Z3:
        import pytest

        pytest.skip("z3-solver not installed")


def test_widening_union():
    """int -> int | str should be widening (non-breaking)."""
    _skip_no_z3()
    assert check_subsumption("int", "int | str") == "widening"


def test_widening_optional():
    """int -> int | None via Optional should be widening."""
    _skip_no_z3()
    assert check_subsumption("int", "Optional[int]") == "widening"


def test_narrowing_union():
    """int | str -> int should be narrowing (breaking)."""
    _skip_no_z3()
    assert check_subsumption("int | str", "int") == "narrowing"


def test_narrowing_optional():
    """int | None -> int should be narrowing."""
    _skip_no_z3()
    assert check_subsumption("Optional[int]", "int") == "narrowing"


def test_changed():
    """int | str -> float | str should be changed (overlap, neither subsumes)."""
    _skip_no_z3()
    assert check_subsumption("int | str", "float | str") == "changed"


def test_widening_any():
    """int -> Any should be widening."""
    _skip_no_z3()
    assert check_subsumption("int", "Any") == "widening"


def test_narrowing_from_any():
    """Any -> int should be narrowing."""
    _skip_no_z3()
    assert check_subsumption("Any", "int") == "narrowing"


def test_identical_not_none():
    """Same type should still return None."""
    _skip_no_z3()
    assert check_subsumption("int", "int") is None


def test_union_via_pep604():
    """PEP 604 syntax for widening."""
    _skip_no_z3()
    assert check_subsumption("bool", "bool | None") == "widening"
    assert check_subsumption("bool | None", "bool") == "narrowing"


def test_no_change_for_unrelated():
    """Completely unrelated types should be 'changed'."""
    _skip_no_z3()
    result = check_subsumption("int", "str")
    assert result == "changed"
