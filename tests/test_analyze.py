import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from impactguard import analyze
from impactguard.impact_analysis import (
    required_positional,
    total_positional,
)


def create_temp_json(data, suffix=".json"):
    """Helper to create a temporary JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        json.dump(data, f)
        return f.name


def test_required_positional():
    """Test counting required positional arguments."""
    func = {
        "positional": [
            {"name": "x", "has_default": False},
            {"name": "y", "has_default": True},
        ]
    }
    assert required_positional(func) == 1


def test_total_positional():
    """Test counting total positional arguments."""
    func = {
        "positional": [
            {"name": "x", "has_default": False},
            {"name": "y", "has_default": True},
        ]
    }
    assert total_positional(func) == 2


def test_analyze_missing_args():
    """Test detecting missing arguments."""
    sigs = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [
                {"name": "x", "has_default": False},
                {"name": "y", "has_default": False},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    calls = [
        {
            "fqname": "test.py:foo",
            "file": "caller.py",
            "lineno": 10,
            "args": 1,
            "kwargs": [],
            "has_starargs": False,
            "has_kwargs": False,
        }
    ]

    sigs_path = create_temp_json(sigs, "sigs.json")
    calls_path = create_temp_json(calls, "calls.json")
    try:
        issues = analyze(sigs_path, calls_path)
        assert len(issues) == 1
        assert issues[0]["risk"] in ["HIGH", "MEDIUM"]
        assert "missing" in issues[0]["change"].lower()
    finally:
        os.unlink(sigs_path)
        os.unlink(calls_path)


def test_analyze_too_many_args():
    """Test detecting too many arguments."""
    sigs = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    calls = [
        {
            "fqname": "test.py:foo",
            "file": "caller.py",
            "lineno": 10,
            "args": 3,
            "kwargs": [],
            "has_starargs": False,
            "has_kwargs": False,
        }
    ]

    sigs_path = create_temp_json(sigs, "sigs.json")
    calls_path = create_temp_json(calls, "calls.json")
    try:
        issues = analyze(sigs_path, calls_path)
        assert len(issues) == 1
        assert "too many" in issues[0]["change"].lower()
    finally:
        os.unlink(sigs_path)
        os.unlink(calls_path)


def test_analyze_with_vararg():
    """Test that *args functions don't flag too many args."""
    sigs = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": True,
            "kwarg": False,
        }
    ]

    calls = [
        {
            "fqname": "test.py:foo",
            "file": "caller.py",
            "lineno": 10,
            "args": 10,
            "kwargs": [],
            "has_starargs": False,
            "has_kwargs": False,
        }
    ]

    sigs_path = create_temp_json(sigs, "sigs.json")
    calls_path = create_temp_json(calls, "calls.json")
    try:
        issues = analyze(sigs_path, calls_path)
        assert len(issues) == 0  # Should not flag with *args
    finally:
        os.unlink(sigs_path)
        os.unlink(calls_path)
