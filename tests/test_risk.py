"""Tests for ImpactGuard risk model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from impactguard import (
    SEVERITY_SCORES,
    classify,
    compute_risk,
    confidence,
    exposure,
    get_severity,
)


def test_get_severity():
    assert get_severity("REMOVED: foo") == 1.0
    assert get_severity("REQUIRED positional arg removed") == 0.9
    assert get_severity("POSITIONAL_REORDER: foo") == 0.8
    assert get_severity("OPTIONAL arg added") == 0.3
    assert get_severity("unknown change") == 0.5


def test_exposure():
    assert exposure(0, 100) == 0
    assert 0 < exposure(1, 100) < 1.0
    assert exposure(100, 100) == 1.0
    assert exposure(1000, 1000) == 1.0


def test_confidence():
    assert confidence(0) == 0.0
    assert confidence(50) == 0.5
    assert confidence(100) == 1.0
    assert confidence(200) == 1.0


def test_classify():
    risk, E, C = classify(0.9, 100, 100, 100)
    assert risk == "HIGH"
    risk, E, C = classify(0.6, 50, 100, 50)
    assert risk == "MEDIUM"
    risk, E, C = classify(0.3, 10, 100, 10)
    assert risk == "UNKNOWN"
    risk, E, C = classify(0.9, 100, 100, 10)
    assert risk == "UNKNOWN"


def test_compute_risk():
    score = compute_risk(0.9, 0.5, 0.8)
    assert score == 0.9 * 0.5 * 0.8


def test_severity_scores():
    assert "REMOVED" in SEVERITY_SCORES
    assert SEVERITY_SCORES["REMOVED"] == 1.0
    assert "REQUIRED" in SEVERITY_SCORES
    assert SEVERITY_SCORES["REQUIRED"] == 0.9
