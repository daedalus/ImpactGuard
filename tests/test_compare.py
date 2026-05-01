"""
Tests for ImpactGuard signature comparison.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from impactguard import compare
from impactguard.compare_signatures import load


def create_temp_json(data, suffix=".json"):
    """Helper to create a temporary JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        json.dump(data, f)
        return f.name


def test_load():
    """Test loading signatures from JSON."""
    data = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
        {
            "fqname": "test.py:bar",
            "name": "bar",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
    ]

    path = create_temp_json(data)
    try:
        result = load(path)
        assert "test.py:foo" in result
        assert "test.py:bar" in result
        assert len(result) == 2
    finally:
        os.unlink(path)


def test_compare_removed():
    """Test detecting removed functions."""
    old = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
        {
            "fqname": "test.py:bar",
            "name": "bar",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
    ]
    new = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    old_path = create_temp_json(old)
    new_path = create_temp_json(new)
    try:
        result = compare(old_path, new_path)
        assert len(result["breaking"]) == 1
        assert "REMOVED" in result["breaking"][0]
        assert "bar" in result["breaking"][0]
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


def test_compare_added():
    """Test detecting added functions."""
    old = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    new = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
        {
            "fqname": "test.py:bar",
            "name": "bar",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
    ]

    old_path = create_temp_json(old)
    new_path = create_temp_json(new)
    try:
        result = compare(old_path, new_path)
        assert len(result["nonbreaking"]) == 1
        assert "ADDED" in result["nonbreaking"][0]
        assert "bar" in result["nonbreaking"][0]
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


def test_compare_positional_removed():
    """Test detecting positional argument removal."""
    old = [
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
    new = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    old_path = create_temp_json(old)
    new_path = create_temp_json(new)
    try:
        result = compare(old_path, new_path)
        assert len(result["breaking"]) == 1
        assert "POSITIONAL REMOVED" in result["breaking"][0]
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


def test_compare_required_added():
    """Test detecting required argument added."""
    old = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    new = [
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

    old_path = create_temp_json(old)
    new_path = create_temp_json(new)
    try:
        result = compare(old_path, new_path)
        assert len(result["breaking"]) == 1
        assert "REQUIRED POSITIONAL ADDED" in result["breaking"][0]
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


def test_compare_optional_added():
    """Test detecting optional argument added."""
    old = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    new = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [
                {"name": "x", "has_default": False},
                {"name": "y", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    old_path = create_temp_json(old)
    new_path = create_temp_json(new)
    try:
        result = compare(old_path, new_path)
        assert len(result["nonbreaking"]) == 1
        assert "OPTIONAL POSITIONAL ADDED" in result["nonbreaking"][0]
    finally:
        os.unlink(old_path)
        os.unlink(new_path)
