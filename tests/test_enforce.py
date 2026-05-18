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


def test_parse_change_line_and_normalize_changes():
    """Structured-risk parsing should normalize text and dict entries consistently."""
    from impactguard.risk_gate import _normalize_changes, _parse_change_line

    parsed = _parse_change_line("REMOVED: pkg/mod.py:foo arg removed")
    assert parsed == {"change": "REMOVED", "function": "pkg/mod.py:foo"}
    assert _parse_change_line("   ") is None
    assert _parse_change_line("missing-colon") is None

    normalized = _normalize_changes(
        [
            "REMOVED: a.py:foo extra text",
            {"change_type": "KWONLY_REMOVED", "fqname": "b.py:bar"},
            {"type": "REQUIRED_KWONLY_ADDED", "symbol": "c.py:baz"},
            {"bad": "entry"},
        ]
    )
    assert {"change": "REMOVED", "function": "a.py:foo"} in normalized
    assert {"change": "KWONLY_REMOVED", "function": "b.py:bar"} in normalized
    assert {"change": "REQUIRED_KWONLY_ADDED", "function": "c.py:baz"} in normalized
