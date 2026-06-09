"""Tests for affected test file detection (affected_tests.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------


class TestIsTestFile:
    def test_test_prefix(self):
        from impactguard.affected_tests import _is_test_file

        assert _is_test_file("tests/test_foo.py")
        assert _is_test_file("/project/test_bar.py")
        assert not _is_test_file("src/foo.py")

    def test_test_suffix(self):
        from impactguard.affected_tests import _is_test_file

        assert _is_test_file("src/foo_test.py")
        assert not _is_test_file("src/bar.py")

    def test_spec_patterns(self):
        from impactguard.affected_tests import _is_test_file

        assert _is_test_file("src/foo.spec.ts")
        assert _is_test_file("src/foo.test.ts")
        assert _is_test_file("src/foo_spec.py")
        assert not _is_test_file("src/spectacular.py")

    def test_tests_dir(self):
        from impactguard.affected_tests import _is_test_file

        assert _is_test_file("/tests/frontend/test_ui.py")
        assert _is_test_file("/e2e/login.py")
        assert _is_test_file("/spec/models.py")
        assert _is_test_file("__tests__/foo.py")
        assert not _is_test_file("src/lib.py")


# ---------------------------------------------------------------------------
# Integration with call graph
# ---------------------------------------------------------------------------


class TestGetAffectedTests:
    def test_returns_affected_tests(self, tmp_path):
        from unittest.mock import MagicMock

        from impactguard.affected_tests import get_affected_tests

        mock_db = MagicMock()
        mock_db.get_affected_tests.return_value = ["tests/test_lib.py"]
        result = get_affected_tests(mock_db, ["src/lib.py"])
        assert result == ["tests/test_lib.py"]
        mock_db.get_affected_tests.assert_called_once_with(
            ["src/lib.py"], depth=5
        )

    def test_empty_changed_files(self, tmp_path):
        from unittest.mock import MagicMock

        from impactguard.affected_tests import get_affected_tests

        mock_db = MagicMock()
        mock_db.get_affected_tests.return_value = []
        result = get_affected_tests(mock_db, [])
        assert result == []

    def test_custom_depth(self, tmp_path):
        from unittest.mock import MagicMock

        from impactguard.affected_tests import get_affected_tests

        mock_db = MagicMock()
        mock_db.get_affected_tests.return_value = ["tests/conftest.py"]
        result = get_affected_tests(mock_db, ["src/core.py"], depth=3)
        assert result == ["tests/conftest.py"]
        mock_db.get_affected_tests.assert_called_once_with(
            ["src/core.py"], depth=3
        )


class TestDescribeAffectedTests:
    def test_describe(self):
        from unittest.mock import MagicMock

        from impactguard.affected_tests import describe_affected_tests

        mock_db = MagicMock()
        mock_db.get_affected_tests.return_value = [
            "tests/test_a.py",
            "tests/test_b.py",
        ]
        result = describe_affected_tests(mock_db, ["src/a.py", "src/b.py"])
        assert result["changed_files"] == ["src/a.py", "src/b.py"]
        assert result["affected_tests"] == ["tests/test_a.py", "tests/test_b.py"]
        assert result["test_count"] == 2
        assert result["traversal_depth"] == 5

    def test_no_tests(self):
        from unittest.mock import MagicMock

        from impactguard.affected_tests import describe_affected_tests

        mock_db = MagicMock()
        mock_db.get_affected_tests.return_value = []
        result = describe_affected_tests(mock_db, ["src/lib.py"])
        assert result["test_count"] == 0
        assert result["affected_tests"] == []
