"""Tests for check_staged pre-commit hook and helpers."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _print_pipeline_summary
# ---------------------------------------------------------------------------


def test_print_pipeline_summary_basic(capsys):
    from impactguard.__main__ import _print_pipeline_summary

    result = {
        "comparison": {
            "breaking": [{"fqname": "foo"}],
            "nonbreaking": [{"fqname": "bar"}],
        },
        "risk": [{"risk": "HIGH"}, {"risk": "LOW"}],
        "analysis_status": {
            "status": "complete",
            "counters": {
                "parse_failures": 0,
                "skipped_files": 0,
                "fallback_used": 0,
                "call_extraction_failures": 0,
                "runtime_data_issues": 0,
            },
        },
    }
    _print_pipeline_summary(result)
    captured = capsys.readouterr().out
    assert "Breaking changes: 1" in captured
    assert "Non-breaking changes: 1" in captured
    assert "HIGH: 1" in captured
    assert "COMPLETE" in captured


def test_print_pipeline_summary_no_risk_gate(capsys):
    from impactguard.__main__ import _print_pipeline_summary

    result = {
        "comparison": {"breaking": [], "nonbreaking": []},
        "analysis_status": {
            "status": "complete",
            "counters": {},
        },
    }
    _print_pipeline_summary(result)
    captured = capsys.readouterr().out
    assert "Breaking changes: 0" in captured
    assert "Non-breaking changes: 0" in captured


def test_print_pipeline_summary_with_gate(capsys):
    from impactguard.__main__ import _print_pipeline_summary

    result = {
        "comparison": {"breaking": [], "nonbreaking": []},
        "gate": {"blocked": True, "reasons": ["policy violation"]},
    }
    _print_pipeline_summary(result)
    captured = capsys.readouterr().out
    assert "Blocked: true" in captured


def test_print_pipeline_summary_with_runtime(capsys):
    from impactguard.__main__ import _print_pipeline_summary

    result = {
        "comparison": {"breaking": [], "nonbreaking": []},
        "analysis_status": {
            "status": "complete",
            "counters": {},
            "runtime": {"state": "partial"},
        },
    }
    _print_pipeline_summary(result)
    captured = capsys.readouterr().out
    assert "Runtime state: partial" in captured


# ---------------------------------------------------------------------------
# _extract_staged_files
# ---------------------------------------------------------------------------


def make_mock_run(responses: dict[str, MagicMock]) -> MagicMock:
    """Create a mock subprocess.run that returns pre-configured results."""

    def side_effect(cmd, **kwargs):
        key = " ".join(cmd)
        for pattern, mock_resp in responses.items():
            if pattern in key:
                return mock_resp
        return MagicMock(returncode=1, stdout="")

    return MagicMock(side_effect=side_effect)


def test_extract_staged_files_success(tmp_path):
    import tempfile

    from impactguard.__main__ import _extract_staged_files

    old_content = "def foo(): pass\n"
    new_content = "def foo(x): pass\n"

    old_mock = MagicMock(returncode=0, stdout=old_content)
    new_mock = MagicMock(returncode=0, stdout=new_content)

    old_stash = tempfile.tempdir
    tempfile.tempdir = str(tmp_path)
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [old_mock, new_mock]

            result = _extract_staged_files(["mymod.py"])

            assert result is not None
            old_paths, new_paths, old_base, new_base = result
            assert len(old_paths) == 1
            assert len(new_paths) == 1
            assert Path(old_paths[0]).read_text() == old_content
            assert Path(new_paths[0]).read_text() == new_content
    finally:
        tempfile.tempdir = old_stash


def test_extract_staged_files_multiple_files(tmp_path):
    import tempfile

    from impactguard.__main__ import _extract_staged_files

    files = ["mod_a.py", "mod_b.py"]
    old_mock_a = MagicMock(returncode=0, stdout="def a(): pass\n")
    new_mock_a = MagicMock(returncode=0, stdout="def a(x): pass\n")
    old_mock_b = MagicMock(returncode=0, stdout="def b(): pass\n")
    new_mock_b = MagicMock(returncode=0, stdout="def b(x): pass\n")

    old_stash = tempfile.tempdir
    tempfile.tempdir = str(tmp_path)
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                old_mock_a,
                new_mock_a,
                old_mock_b,
                new_mock_b,
            ]

            result = _extract_staged_files(files)

            assert result is not None
            old_paths, new_paths, _, _ = result
            assert len(old_paths) == 2
            assert len(new_paths) == 2
    finally:
        tempfile.tempdir = old_stash


def test_extract_staged_files_git_show_fails(tmp_path):
    import tempfile

    from impactguard.__main__ import _extract_staged_files

    old_mock = MagicMock(returncode=128, stdout="")
    new_mock = MagicMock(returncode=0, stdout="def foo(): pass\n")

    old_stash = tempfile.tempdir
    tempfile.tempdir = str(tmp_path)
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [old_mock, new_mock]

            result = _extract_staged_files(["mymod.py"])

            assert result is not None
            old_paths, new_paths, _, _ = result
            assert len(old_paths) == 0
            assert len(new_paths) == 1
    finally:
        tempfile.tempdir = old_stash


def test_extract_staged_files_no_new_files(tmp_path):
    import tempfile

    from impactguard.__main__ import _extract_staged_files

    old_mock = MagicMock(returncode=0, stdout="def foo(): pass\n")
    new_mock = MagicMock(returncode=128, stdout="")

    old_stash = tempfile.tempdir
    tempfile.tempdir = str(tmp_path)
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [old_mock, new_mock]

            result = _extract_staged_files(["mymod.py"])

            assert result is None
    finally:
        tempfile.tempdir = old_stash


def test_extract_staged_files_with_subdir(tmp_path):
    import tempfile

    from impactguard.__main__ import _extract_staged_files

    old_content = "def foo(): pass\n"
    new_content = "def foo(x): pass\n"

    old_mock = MagicMock(returncode=0, stdout=old_content)
    new_mock = MagicMock(returncode=0, stdout=new_content)

    old_stash = tempfile.tempdir
    tempfile.tempdir = str(tmp_path)
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [old_mock, new_mock]

            result = _extract_staged_files(["subdir/mymod.py"])

            assert result is not None
            old_paths, _, old_base, _ = result
            old_path = Path(old_paths[0])
            assert old_path.exists()
            assert old_path.read_text() == old_content
    finally:
        tempfile.tempdir = old_stash


# ---------------------------------------------------------------------------
# check_staged
# ---------------------------------------------------------------------------


def test_check_staged_skip_hook():
    from impactguard.__main__ import check_staged

    with patch.dict(os.environ, {"SKIP_SIGNATURE_HOOK": "1"}):
        assert check_staged() == 0


def test_check_staged_no_staged_changes():
    from impactguard.__main__ import check_staged

    diff_mock = MagicMock(returncode=0, stdout="")
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("subprocess.run", return_value=diff_mock),
    ):
        assert check_staged() == 0


def test_check_staged_no_py_files():
    from impactguard.__main__ import check_staged

    diff_mock = MagicMock(returncode=0, stdout="README.md\nMakefile\n")
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("subprocess.run", return_value=diff_mock),
    ):
        assert check_staged() == 0


def test_check_staged_pipeline_not_blocked():
    from impactguard.__main__ import check_staged

    diff_mock = MagicMock(returncode=0, stdout="src/mymod.py\n")
    show_mock = MagicMock(returncode=0, stdout="def foo(): pass\n")

    def fake_run_pipeline(**kwargs):
        return {
            "comparison": {"breaking": [], "nonbreaking": [{"fqname": "foo"}]},
            "risk": [],
            "analysis_status": {"status": "complete", "counters": {}},
            "gate": {"blocked": False},
        }

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("subprocess.run") as mock_run,
        patch("impactguard.pipeline.run_pipeline", side_effect=fake_run_pipeline),
    ):
        mock_run.side_effect = [
            diff_mock,
            show_mock,
            show_mock,
        ]
        assert check_staged() == 0


def test_check_staged_pipeline_blocked():
    from impactguard.__main__ import check_staged

    diff_mock = MagicMock(returncode=0, stdout="src/mymod.py\n")
    show_mock = MagicMock(returncode=0, stdout="def foo(): pass\n")

    def fake_run_pipeline(**kwargs):
        return {
            "comparison": {"breaking": [{"fqname": "foo"}]},
            "risk": [{"risk": "HIGH"}],
            "analysis_status": {"status": "complete", "counters": {}},
            "gate": {"blocked": True, "reasons": ["breaking change"]},
        }

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("subprocess.run") as mock_run,
        patch("impactguard.pipeline.run_pipeline", side_effect=fake_run_pipeline),
    ):
        mock_run.side_effect = [
            diff_mock,
            show_mock,
            show_mock,
        ]
        assert check_staged() == 1


def test_check_staged_extract_fails_returns_zero():
    from impactguard.__main__ import check_staged

    diff_mock = MagicMock(returncode=0, stdout="src/mymod.py\n")
    show_mock = MagicMock(returncode=128, stdout="")

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.side_effect = [
            diff_mock,
            show_mock,
            show_mock,
        ]
        assert check_staged() == 0


def test_check_staged_prints_result(capsys):
    from impactguard.__main__ import check_staged

    diff_mock = MagicMock(returncode=0, stdout="src/mymod.py\n")
    show_mock = MagicMock(returncode=0, stdout="def foo(): pass\n")

    def fake_run_pipeline(**kwargs):
        return {
            "comparison": {"breaking": [{"fqname": "foo"}], "nonbreaking": []},
            "risk": [{"risk": "HIGH"}],
            "analysis_status": {"status": "complete", "counters": {}},
            "gate": {"blocked": True},
        }

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("subprocess.run") as mock_run,
        patch("impactguard.pipeline.run_pipeline", side_effect=fake_run_pipeline),
    ):
        mock_run.side_effect = [
            diff_mock,
            show_mock,
            show_mock,
        ]
        check_staged()
        captured = capsys.readouterr().out
        assert "Breaking changes: 1" in captured
        assert "HIGH: 1" in captured
        assert "Blocked: true" in captured
