"""Tests for enforce_gate module."""

import json
import os
import tempfile

from impactguard.enforce_gate import enforce_report


def test_enforce_no_high_risk():
    """Test enforce with no HIGH risk items."""
    report_data = [
        {
            "function": "test.py:foo",
            "risk": "LOW",
            "change": "ADDED",
        }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(report_data, f)
        report_file = f.name

    result = enforce_report(report_file)
    # No HIGH risk, should return 0
    assert result == 0
    os.unlink(report_file)


def test_enforce_with_high_risk():
    """Test enforce with HIGH risk items."""
    report_data = [
        {
            "function": "test.py:foo",
            "risk": "HIGH",
            "change": "REMOVED",
        }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(report_data, f)
        report_file = f.name

    result = enforce_report(report_file)
    # Has HIGH risk, should return 1
    assert result == 1
    os.unlink(report_file)
