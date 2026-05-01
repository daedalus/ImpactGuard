"""
Tests for ImpactGuard signature extraction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from impactguard import serialize_function


def test_serialize_function():
    """Test serializing a function node."""
    import ast

    code = "def foo(x, y=1): pass"
    tree = ast.parse(code)
    func = tree.body[0]

    result = serialize_function(func, "test.py")

    assert result["name"] == "foo"
    assert result["fqname"] == "test.py:foo"
    assert len(result["positional"]) == 2
    assert result["positional"][0]["name"] == "x"
    assert result["positional"][0]["has_default"] == False
    assert result["positional"][1]["name"] == "y"
    assert result["positional"][1]["has_default"] == True
    assert result["vararg"] == False
    assert result["kwarg"] == False
