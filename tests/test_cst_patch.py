"""Tests for CST patch module."""

from unittest.mock import patch as mock_patch

import pytest

from impactguard.cst_patch import LIBCST_AVAILABLE, patch_call, patch_function


def test_cst_available():
    assert LIBCST_AVAILABLE is True


def test_patch_function_non_matching_name():
    source = "def bar(x): pass\n"
    result, error = patch_function(source, "foo", "x")
    assert result == source
    assert error is None


def test_patch_call_non_matching_name():
    source = "bar(1)\n"
    result, error = patch_call(source, "foo", "x")
    assert result == source
    assert error is None


def test_patch_call_with_kwarg_already_present():
    source = "foo(x=1)\n"
    result, error = patch_call(source, "foo", "x")
    assert result == source
    assert error is None


def test_patch_call_adds_new_arg():
    source = "foo(1)\n"
    result, error = patch_call(source, "foo", "y")
    assert error is None
    assert "y" in result
    assert result != source


def test_patch_function_libcst_not_available():
    with mock_patch("impactguard.cst_patch.LIBCST_AVAILABLE", False):
        result, error = patch_function("def foo(x): pass\n", "foo", "x")
        assert result is None
        assert error == "libcst not installed"


def test_patch_call_libcst_not_available():
    with mock_patch("impactguard.cst_patch.LIBCST_AVAILABLE", False):
        result, error = patch_call("foo(1)\n", "foo", "x")
        assert result is None
        assert error == "libcst not installed"


def test_patch_function_adds_default():
    source = "def foo(x, y): pass\n"
    result, error = patch_function(source, "foo", "y")
    assert error is None
    assert "None" in result


def test_patch_function_exception():
    with mock_patch("impactguard.cst_patch.cst.parse_module", side_effect=RuntimeError("parse failed")):
        result, error = patch_function("def foo(x): pass\n", "foo", "x")
        assert result is None
        assert error == "parse failed"
