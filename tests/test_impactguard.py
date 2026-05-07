"""
Tests for ImpactGuard components.
"""

import json
import os
import tempfile

from impactguard.compare_signatures import compare
from impactguard.extract_signatures import extract, serialize_function


def test_signature_extraction():
    """Test that extract() works."""
    # Use the current file as input
    import inspect

    current_file = inspect.getfile(inspect.currentframe())

    result = extract([current_file])
    assert len(result) > 0, "No signatures extracted"
    assert any(f["name"] == "test_signature_extraction" for f in result)


def test_serialize_function():
    """Test serialize_function output format."""
    import ast

    code = "def foo(x, y=10, *args, **kwargs): pass"
    tree = ast.parse(code)
    func_node = tree.body[0]

    result = serialize_function(func_node, "test.py")
    assert result["name"] == "foo"
    assert result["fqname"] == "test.py:foo"
    assert len(result["positional"]) == 2  # x, y (args and kwargs are separate)
    assert result["vararg"] is True
    assert result["kwarg"] is True


def test_compare_signatures():
    """Test that compare() works."""
    sigs1 = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "file": "test.py",
            "lineno": 1,
            "end_lineno": 1,
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    sigs2 = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "file": "test.py",
            "lineno": 1,
            "end_lineno": 1,
            "positional": [
                {"name": "x", "has_default": False},
                {"name": "y", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f1:
        json.dump(sigs1, f1)
        f1_name = f1.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f2:
        json.dump(sigs2, f2)
        f2_name = f2.name

    result = compare(f1_name, f2_name)

    os.unlink(f1_name)
    os.unlink(f2_name)

    assert "OPTIONAL_POSITIONAL_ADDED" in str(result["nonbreaking"])
