"""Tests for pipeline.py - Integration tests for ImpactGuard."""

import json
import os
from pathlib import Path


def test_pipeline_import():
    """Test that pipeline components can be imported."""
    from impactguard.pipeline import ImpactGuard, quick_check, run_pipeline

    assert callable(run_pipeline)
    assert callable(quick_check)
    assert hasattr(ImpactGuard, "__init__")


def test_impactguard_class():
    """Test ImpactGuard class API."""
    from impactguard import ImpactGuard

    # Test initialization
    guard = ImpactGuard()
    assert guard.config == {}

    # Test with config
    config = {"risk": {"confidence_threshold": 0.3}}
    guard_with_config = ImpactGuard(config)
    assert guard_with_config.config == config


def test_quick_check_missing_files():
    """Test quick_check with missing files."""
    from impactguard.pipeline import quick_check

    # Should raise ValueError when no signatures provided
    try:
        quick_check("/nonexistent/path", "/another/nonexistent")
    except ValueError:
        pass  # Expected


def test_full_pipeline_with_real_files(tmp_path):
    """Test full pipeline with real Python files."""
    from impactguard.pipeline import run_pipeline

    # Create old version
    old_file = tmp_path / "old_module.py"
    old_file.write_text("""
def hello(name):
    return f"Hello {name}"

def add(a, b):
    return a + b

class Calculator:
    def multiply(self, x, y):
        return x * y
""")

    # Create new version (with changes)
    new_file = tmp_path / "new_module.py"
    new_file.write_text("""
def hello(name, greeting="Hello"):
    return f"{greeting} {name}"

def add(a, b, c=0):  # Added optional param
    return a + b + c

class Calculator:
    def multiply(self, x, y):
        return x * y

def new_function():  # Added function
    pass
""")

    # Run pipeline
    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        output_dir=str(tmp_path / "output"),
    )

    # Check that result has expected keys
    assert "comparison" in result
    assert "impact" in result
    assert "risk" in result
    assert "report_html" in result
    assert "fixes" in result

    # Check that comparison detected changes
    comparison = result["comparison"]
    assert "breaking" in comparison
    assert "nonbreaking" in comparison

    # Should detect new function as non-breaking
    assert len(comparison["nonbreaking"]) > 0


def test_impactguard_analyze(tmp_path):
    """Test ImpactGuard.analyze method."""
    from impactguard import ImpactGuard

    guard = ImpactGuard()

    # Create test files
    old_file = tmp_path / "module.py"
    old_file.write_text("def foo(a, b): return a + b\n")

    new_file = tmp_path / "module_new.py"
    new_file.write_text("def foo(a, b, c=0): return a + b + c\n")

    # Analyze
    result = guard.analyze(str(old_file), str(new_file))

    assert "signatures" in result
    assert "comparison" in result


def test_impactguard_extract(tmp_path):
    """Test ImpactGuard.extract method."""
    from impactguard import ImpactGuard

    guard = ImpactGuard()

    # Create test file
    test_file = tmp_path / "test.py"
    test_file.write_text("""
def func1():
    pass

def func2(a, b=1):
    return a + b
""")

    result = guard.extract([str(test_file)])

    assert isinstance(result, list)
    assert len(result) >= 2

    # Check signature format
    sig = result[0]
    assert "fqname" in sig
    assert "name" in sig
    assert "positional" in sig


def test_impactguard_compare(tmp_path):
    """Test ImpactGuard.compare method."""
    from impactguard import ImpactGuard

    guard = ImpactGuard()

    # Create signature files
    old_sigs = [
        {
            "fqname": "test.py:func",
            "name": "func",
            "positional": [{"name": "a", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    new_sigs = [
        {
            "fqname": "test.py:func",
            "name": "func",
            "positional": [
                {"name": "a", "has_default": False},
                {"name": "b", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
        {
            "fqname": "test.py:new_func",
            "name": "new_func",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
    ]

    old_file = tmp_path / "old.json"
    new_file = tmp_path / "new.json"
    old_file.write_text(json.dumps(old_sigs))
    new_file.write_text(json.dumps(new_sigs))

    result = guard.compare(str(old_file), str(new_file))

    assert "breaking" in result
    assert "nonbreaking" in result


def test_config_file():
    """Test that impactguard.toml is present in the repository root."""
    repo_root = Path(__file__).parent.parent
    config_path = repo_root / "impactguard.toml"

    # Check that config file exists
    assert config_path.exists(), "impactguard.toml not found"

    # Read and validate
    content = config_path.read_text()
    assert "[impactguard]" in content


def test_cli_check_command(tmp_path):
    """Test CLI check command exists."""
    import subprocess
    import sys

    # Check that the check command is available
    result = subprocess.run(
        [sys.executable, "-m", "impactguard", "check", "--help"],
        capture_output=True,
        text=True,
    )

    # Should not crash
    assert result.returncode in [0, 1]  # 0 if help shown, 1 if argparse exits


def test_end_to_end_workflow(tmp_path):
    """Test complete end-to-end workflow."""
    from impactguard.pipeline import quick_check

    # Create test project
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Old version
    (project_dir / "calc.py").write_text("""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

class Math:
    def multiply(self, x, y):
        return x * y
""")

    # New version with changes
    (project_dir / "calc_new.py").write_text("""
def add(a, b, debug=False):  # Added optional param
    return a + b

# subtract removed (breaking!)

class Math:
    def multiply(self, x, y):
        return x * y

def divide(a, b):  # New function
    return a / b
""")

    # Run quick check
    result = quick_check(str(project_dir / "calc.py"), str(project_dir / "calc_new.py"))

    assert "comparison" in result
    assert "risk" in result
    assert "report_html" in result

    # Check that HTML was generated
    html = result["report_html"]
    assert "HIGH" in html or "MEDIUM" in html or "LOW" in html


def test_pipeline_comparison_breaking(tmp_path):
    """Test that breaking changes are detected."""
    from impactguard.pipeline import run_pipeline

    # Old: function with 2 required args
    old_file = tmp_path / "old.py"
    old_file.write_text("def process(data, options): return data\n")

    # New: removed required arg (breaking!)
    new_file = tmp_path / "new.py"
    new_file.write_text("def process(data): return data\n")

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        output_dir=str(tmp_path / "output"),
    )

    comparison = result["comparison"]
    breaking = comparison["breaking"]

    # Should detect breaking change
    assert len(breaking) > 0, f"Expected breaking changes, got: {breaking}"

    # Check that it contains REMOVED
    found = False
    for change in breaking:
        if "REMOVED" in change or "POSITIONAL" in change:
            found = True
            break

    assert found, f"Expected REMOVED in breaking changes, got: {breaking}"
