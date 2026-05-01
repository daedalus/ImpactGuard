"""Tests for runtime_impact module."""

import json
import tempfile

from impactguard.runtime_impact import load_funcs


def test_load_funcs():
    """Test load_funcs function."""
    sigs_data = [
        {"fqname": "test.py:foo", "name": "foo", "positional": [{"name": "x", "has_default": False}]}
    ]

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sigs_data, f)
        f.name

    result = load_funcs(f.name)
    assert "test.py:foo" in result

    import os
    os.unlink(f.name)


def test_required_positional():
    """Test required_positional function."""
    from impactguard.runtime_impact import required_positional
    f = {"positional": [{"name": "x", "has_default": False}, {"name": "y", "has_default": True}]}
    result = required_positional(f)
    assert result == 1  # Only x is required


def test_total_positional():
    """Test total_positional function."""
    from impactguard.runtime_impact import total_positional
    f = {"positional": [{"name": "x"}, {"name": "y"}]}
    result = total_positional(f)
    assert result == 2
