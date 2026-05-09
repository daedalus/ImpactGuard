"""Tests for ImpactGuard functionality."""

from __future__ import annotations

import json
import os  
import sys
import tempfile  
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_generate_report_final(tmp_path):
    """Final coverage push for generate_report.py."""
    from impactguard.generate_report import generate_html

    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
    ]

    result = generate_html(items)
    assert "HIGH" in result

def test_generate_report_deep_coverage(tmp_path):
    """Cover more lines in generate_report.py."""
    from impactguard.generate_report import generate_html

    # Test with various items
    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
        {"fqname": "test:bar", "risk_level": "MEDIUM", "change": "ADDED"},
        {"fqname": "test:baz", "risk_level": "LOW", "change": "NONE"},
    ]

    result = generate_html(items)
    assert "HIGH" in result
    assert "MEDIUM" in result
    assert "LOW" in result

def test_generate_report_complex(tmp_path):
    """Test generate_report with complex data."""
    from impactguard.generate_report import generate_html

    items = [
        {
            "fqname": "test.py:foo",
            "risk_level": "HIGH",
            "change": "POSITIONAL_REMOVED",
            "confidence": 0.9,
            "exposure": 0.8,
        },
        {
            "fqname": "test.py:bar",
            "risk_level": "MEDIUM",
            "change": "OPTIONAL ADDED",
            "confidence": 0.6,
            "exposure": 0.4,
        },
    ]

    result = generate_html(items)
    assert "HIGH" in result
    assert "MEDIUM" in result

def test_generate_report_coverage_final(tmp_path):
    """Target missing lines in generate_report.py."""
    from impactguard.generate_report import generate_html

    # Test with items
    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
    ]

    result = generate_html(items)
    assert "HIGH" in result

def test_generate_changelog_with_files(tmp_path):
    """Test generate_changelog function."""
    from impactguard.pipeline import generate_changelog

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a, b): return a + b\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b, c=0): return a + b + c\n")

    changelog = generate_changelog(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
    )

    assert "## [Unreleased]" in changelog
    assert "foo" in changelog

def test_generate_changelog_output_path(tmp_path):
    """Test generate_changelog with output path."""
    from impactguard.pipeline import generate_changelog

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(): pass\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(x): pass\n")

    output_path = tmp_path / "CHANGELOG.md"

    changelog = generate_changelog(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        output_path=str(output_path),
    )

    assert output_path.exists()
    assert "## [Unreleased]" in output_path.read_text()

# =======================================

def test_generate_report_full_coverage(tmp_path):
    """Test generate_report module fully."""
    from impactguard.generate_report import generate_html

    # Test with empty list
    result = generate_html([])
    assert isinstance(result, str)

    # Test with single item
    result = generate_html([{"fqname": "test:foo", "risk_level": "LOW"}])
    assert isinstance(result, str)

    # Test with multiple items
    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
        {"fqname": "test:bar", "risk_level": "MEDIUM", "change": "ADDED"},
        {"fqname": "test:baz", "risk_level": "LOW", "change": "NONE"},
    ]
    result = generate_html(items)
    assert "HIGH" in result
    assert "MEDIUM" in result
    assert "LOW" in result

def test_generate_report_coverage_push(tmp_path):
    """Push generate_report.py coverage up."""
    from impactguard.generate_report import generate_html

    # Test with empty list
    result = generate_html([])
    assert isinstance(result, str)

    # Test with items
    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
        {"fqname": "test:bar", "risk_level": "LOW", "change": "ADDED"},
    ]
    result = generate_html(items)
    assert "HIGH" in result
    assert "LOW" in result

