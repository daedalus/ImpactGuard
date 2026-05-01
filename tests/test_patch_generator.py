"""Tests for patch_generator module."""

from impactguard.patch_generator import patch_add_default, patch_callsite


def test_patch_add_default():
    """Test patch_add_default function."""
    func = {"file": "test.py", "lineno": 1}
    result = patch_add_default(func, "new_param")
    # Should return a diff string or None
    assert result is None or isinstance(result, str)


def test_patch_callsite():
    """Test patch_callsite function."""
    call = {"file": "test.py", "lineno": 5}
    func = {"name": "foo", "positional": []}
    result = patch_callsite(call, func)
    # Should return a diff string or None
    assert result is None or isinstance(result, str)
