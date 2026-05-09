"""Tests for ImpactGuard functionality."""

from __future__ import annotations

import json
import os  
import sys
import tempfile  
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_run_pipeline_with_calls_path(tmp_path):
    """Test run_pipeline with provided calls_path."""
    from impactguard.pipeline import run_pipeline

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a): return a\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b=1): return a + b\n")

    calls_data = [{"fqname": "test.py:foo", "file": "main.py", "lineno": 5}]
    calls_path = tmp_path / "calls.json"
    calls_path.write_text(json.dumps(calls_data))

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        calls_path=str(calls_path),
        output_dir=str(tmp_path / "output"),
    )

    assert "impact" in result

def test_run_pipeline_with_runtime_path(tmp_path):
    """Test run_pipeline with runtime data."""
    from impactguard.pipeline import run_pipeline

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a): return a\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b=1): return a + b\n")

    runtime_data = [{"function": "foo", "args_count": 1, "kwargs": []}]
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps(runtime_data))

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        runtime_path=str(runtime_path),
        output_dir=str(tmp_path / "output"),
    )

    assert "risk" in result

def test_run_pipeline_with_old_files(tmp_path):
    """Test run_pipeline with old_files parameter."""
    from impactguard.pipeline import run_pipeline

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a, b): return a + b\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b, c=0): return a + b + c\n")

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        output_dir=str(tmp_path / "output"),
    )

    assert "comparison" in result
    assert "signatures" in result

def test_run_pipeline_with_sigs_path(tmp_path):
    """Test run_pipeline with signature paths."""
    from impactguard.extract_signatures import extract
    from impactguard.pipeline import run_pipeline

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a, b): return a + b\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b, c=0): return a + b + c\n")

    old_sigs = extract([str(old_file)])
    new_sigs = extract([str(new_file)])

    old_path = tmp_path / "old_sigs.json"
    new_path = tmp_path / "new_sigs.json"
    old_path.write_text(json.dumps(old_sigs))
    new_path.write_text(json.dumps(new_sigs))

    result = run_pipeline(
        old_sigs_path=str(old_path),
        new_sigs_path=str(new_path),
        output_dir=str(tmp_path / "output"),
    )

    assert "comparison" in result

def test_run_pipeline_no_old_sigs(tmp_path):
    """Test run_pipeline with no old signatures."""
    from impactguard.pipeline import run_pipeline

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b): return a + b\n")

    result = run_pipeline(
        new_files=[str(new_file)],
        output_dir=str(tmp_path / "output"),
    )

    assert "signatures" in result
    assert "new" in result["signatures"]

def test_run_pipeline_with_runtime(tmp_path):
    """Test run_pipeline with runtime data."""
    from impactguard.pipeline import run_pipeline

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a, b): return a + b\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b, c=0): return a + b + c\n")

    runtime_data = [{"function": "foo", "args_count": 2, "kwargs": []}]
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps(runtime_data))

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        runtime_path=str(runtime_path),
        output_dir=str(tmp_path / "output"),
    )

    assert "risk" in result

def test_run_pipeline_git_with_files(tmp_path):
    """Test run_pipeline_git with specific files."""
    from impactguard.pipeline import run_pipeline_git

    # Mock git operations
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(  # noqa: V101
            returncode=0,
            stdout="module.py\n",
            stderr="",
        )

        with patch("pathlib.Path.exists", return_value=True):
            with patch("impactguard.pipeline.run_pipeline") as mock_pipeline:
                mock_pipeline.return_value = {"comparison": {}, "signatures": {}}  # noqa: V101

                result = run_pipeline_git(
                    old_ref="HEAD~1",
                    new_ref="HEAD",
                    files=["module.py"],
                    output_path=str(tmp_path / "output"),
                )

                assert "comparison" in result

