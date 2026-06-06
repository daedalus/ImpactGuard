"""Tests for patch_confidence module."""

from unittest.mock import patch as mock_patch

import pytest

from impactguard.patch_confidence import (
    _cfg,
    _classify_strict,
    classify as classify_patch,
    classify_with_factors,
    compute_confidence,
    get_complexity_penalty,
    get_semantic_risk,
    get_structural_safety,
    get_target_certainty,
    score,
)


def test_compute_confidence():
    """Test compute_confidence function."""
    result = compute_confidence(0.9, 0.8, 0.7, 0.9)
    expected = 0.9 * 0.8 * 0.7 * 0.9
    assert result == expected


def test_classify_patch_high():
    """Test classify_patch with high confidence."""
    result = classify_patch(0.9)
    assert result == "HIGH"


def test_classify_patch_medium():
    """Test classify_patch with medium confidence."""
    result = classify_patch(0.6)
    assert result == "MEDIUM"


def test_classify_patch_low():
    """Test classify_patch with low confidence."""
    result = classify_patch(0.3)
    assert result == "LOW"


def test_classify_patch_unknown():
    """Test classify_patch with unknown confidence."""
    result = classify_patch(0.1)
    assert result == "UNKNOWN"


def test_classify_patch_zero():
    """Test classify_patch with exactly zero."""
    result = classify_patch(0.0)
    assert result == "LOW"


def test_score():
    """Test score delegates to compute_confidence."""
    result = score(0.9, 0.8, 0.7, 0.9)
    assert result == 0.9 * 0.8 * 0.7 * 0.9


def test_classify_strict_high():
    assert _classify_strict(0.75) == "HIGH"


def test_classify_strict_medium():
    assert _classify_strict(0.4) == "MEDIUM"


def test_classify_strict_low():
    assert _classify_strict(0.2) == "LOW"


def test_classify_strict_unknown():
    assert _classify_strict(0.1) == "UNKNOWN"


def test_cfg_default():
    assert _cfg("nonexistent.key", 0.5) == 0.5


def test_cfg_exception():
    with mock_patch("impactguard.config.get", side_effect=AttributeError):
        assert _cfg("some.key", 0.5) == 0.5


def test_get_target_certainty_file_lineno_match():
    result = get_target_certainty(file_match=True, lineno_match=True, name_only_match=False)
    assert result >= 1.0


def test_get_target_certainty_name_only():
    result = get_target_certainty(file_match=False, lineno_match=False, name_only_match=True)
    assert result > 0


def test_get_target_certainty_no_match():
    result = get_target_certainty(file_match=False, lineno_match=False, name_only_match=False)
    assert result > 0


def test_get_structural_safety_default():
    result = get_structural_safety("OPTIONAL_ADDED")
    assert result >= 1.0


def test_get_structural_safety_optional():
    result = get_structural_safety("PARAMETER_OPTIONAL")
    assert result >= 1.0


def test_get_structural_safety_kwarg():
    result = get_structural_safety("KWARG_ADDED")
    assert result >= 0.8


def test_get_structural_safety_positional():
    result = get_structural_safety("POSITIONAL_REMOVED")
    assert result >= 0.3


def test_get_structural_safety_other():
    result = get_structural_safety("SOMETHING_ELSE")
    assert result == 0.5


def test_get_semantic_risk_required():
    result = get_semantic_risk("REQUIRED_POSITIONAL_ADDED")
    assert result < 1.0


def test_get_semantic_risk_default():
    result = get_semantic_risk("OPTIONAL_ADDED")
    assert result == 1.0


def test_get_complexity_penalty_none():
    result = get_complexity_penalty(False, False, False, False)
    assert result == 1.0


def test_get_complexity_penalty_multiline():
    result = get_complexity_penalty(True, False, False, False)
    assert result < 1.0


def test_get_complexity_penalty_decorators():
    result = get_complexity_penalty(False, True, False, False)
    assert result < 1.0


def test_get_complexity_penalty_annotations():
    result = get_complexity_penalty(False, False, True, False)
    assert result < 1.0


def test_get_complexity_penalty_nested():
    result = get_complexity_penalty(False, False, False, True)
    assert result < 1.0


def test_get_complexity_penalty_all():
    result = get_complexity_penalty(True, True, True, True)
    assert result < 1.0


def test_classify_with_factors():
    level, factors = classify_with_factors(1.0, 1.0, 0.9, 1.0)
    assert level == "HIGH"
    assert factors["target"] == 1.0
    assert factors["structure"] == 1.0
    assert factors["semantic"] == 0.9
    assert factors["complexity"] == 1.0
    assert factors["final"] == 0.9
