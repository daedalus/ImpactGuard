"""Tests to boost coverage for pipeline.py."""

import json
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import MagicMock, patch


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


def test_quick_check_single_file(tmp_path):
    """Test quick_check with single files."""
    from impactguard.pipeline import quick_check

    old_file = tmp_path / "old.py"
    old_file.write_text("def hello(name): return f'Hello {name}'\n")

    new_file = tmp_path / "new.py"
    new_file.write_text(
        "def hello(name, greeting='Hello'): return f'{greeting} {name}'\n"
    )

    result = quick_check(str(old_file), str(new_file))

    assert "comparison" in result
    assert "signatures" in result


def test_quick_check_directory(tmp_path):
    """Test quick_check with directories."""
    from impactguard.pipeline import quick_check

    old_dir = tmp_path / "old"
    old_dir.mkdir()
    (old_dir / "module.py").write_text("def foo(): pass\n")

    new_dir = tmp_path / "new"
    new_dir.mkdir()
    (new_dir / "module.py").write_text("def foo(x=None): pass\n")

    result = quick_check(str(old_dir), str(new_dir))

    assert "comparison" in result


def test_quick_check_missing_file():
    """Test quick_check with missing files."""
    from impactguard.pipeline import quick_check

    try:
        quick_check("/nonexistent/path", "/another/nonexistent")
    except ValueError:
        pass  # Expected


def test_impactguard_class_methods(tmp_path):
    """Test ImpactGuard class methods."""
    from impactguard import ImpactGuard

    guard = ImpactGuard()
    assert guard.config == {}

    # Test analyze
    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a): return a\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b=1): return a + b\n")

    result = guard.analyze(str(old_file), str(new_file))
    assert "signatures" in result

    # Test extract
    test_file = tmp_path / "test.py"
    test_file.write_text("def bar(): pass\n")
    sigs = guard.extract([str(test_file)])
    assert isinstance(sigs, list)

    # Test compare
    old_sigs = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [{"name": "a", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    new_sigs = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [
                {"name": "a", "has_default": False},
                {"name": "b", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old_sigs))
    new_path.write_text(json.dumps(new_sigs))

    result = guard.compare(str(old_path), str(new_path))
    assert "breaking" in result
    assert "nonbreaking" in result


def test_impactguard_check_method(tmp_path):
    """Test ImpactGuard.check method."""
    from impactguard import ImpactGuard

    guard = ImpactGuard()

    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(a, b): return a + b\n")

    result = guard.check(str(test_file))
    assert "signatures" in result
    assert "status" in result


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
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="module.py\n",
            stderr="",
        )

        with patch("pathlib.Path.exists", return_value=True):
            with patch("impactguard.pipeline.run_pipeline") as mock_pipeline:
                mock_pipeline.return_value = {"comparison": {}, "signatures": {}}

                result = run_pipeline_git(
                    old_ref="HEAD~1",
                    new_ref="HEAD",
                    files=["module.py"],
                    output_path=str(tmp_path / "output"),
                )

                assert "comparison" in result


def test_generate_changelog_with_files(tmp_path):
    """Test generate_changelog function."""
    from impactguard.pipeline import generate_changelog

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a, b): return a + b\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b, c=0): return a + b + c\n")

    changelog = generate_changelog(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
    )

    assert "## [Unreleased]" in changelog
    assert "foo" in changelog


def test_generate_changelog_output_path(tmp_path):
    """Test generate_changelog with output path."""
    from impactguard.pipeline import generate_changelog

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(): pass\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(x): pass\n")

    output_path = tmp_path / "CHANGELOG.md"

    changelog = generate_changelog(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        output_path=str(output_path),
    )

    assert output_path.exists()
    assert "## [Unreleased]" in output_path.read_text()
