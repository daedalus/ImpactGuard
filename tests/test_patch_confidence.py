"""Tests for patch_confidence module."""

from impactguard.patch_confidence import (
    classify as classify_patch,
)
from impactguard.patch_confidence import (
    compute_confidence,
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
