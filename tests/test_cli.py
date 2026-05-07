"""
Tests for ImpactGuard CLI.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from impactguard.__main__ import main as cli_main


def run_cli(args):
    """Helper to run CLI with arguments."""
    old_argv = sys.argv[:]
    sys.argv = ["impactguard"] + args
    try:
        result = cli_main()
        return result or 0
    except SystemExit as e:
        return e.code or 0
    finally:
        sys.argv = old_argv


def create_temp_file(content, suffix=".py"):
    """Create a temporary file with content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(content)
        return f.name


def test_cli_help():
    """Test CLI help output."""
    # Just verify the CLI module can be imported and has subcommands
    from impactguard.__main__ import main as cli_main

    assert hasattr(cli_main, "__call__")


def test_cli_version():
    """Test CLI version flag."""
    result = run_cli(["--version"])
    # Version should exit with 0
    assert result == 0


def test_extract_command():
    """Test extract command."""
    code = "def foo(x, y=1): pass\ndef bar(z): pass\n"
    temp_file = create_temp_file(code)

    try:
        result = run_cli(["extract", temp_file])
        assert result == 0
    finally:
        os.unlink(temp_file)


def test_compare_command():
    """Test compare command."""
    old_data = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    new_data = [
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

    old_file = create_temp_file(json.dumps(old_data), ".json")
    new_file = create_temp_file(json.dumps(new_data), ".json")

    try:
        result = run_cli(["compare", "--json", old_file, new_file])
        # Should detect non-breaking change
        assert result == 0
    finally:
        os.unlink(old_file)
        os.unlink(new_file)


def test_analyze_command():
    """Test analyze command."""
    sigs_data = [
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
    calls_data = [
        {
            "fqname": "test.py:foo",
            "file": "caller.py",
            "lineno": 10,
            "args": 1,
            "kwargs": [],
            "has_starargs": False,
            "has_kwargs": False,
        }
    ]

    sigs_file = create_temp_file(json.dumps(sigs_data), ".json")
    calls_file = create_temp_file(json.dumps(calls_data), ".json")

    try:
        result = run_cli(["analyze", sigs_file, calls_file])
        # analyze command returns 0 regardless of risk level
        assert result == 0
    finally:
        os.unlink(sigs_file)
        os.unlink(calls_file)


def test_risk_command():
    """Test risk command."""
    diff_text = "REMOVED: test.py:foo\n"
    diff_file = create_temp_file(diff_text)

    runtime_data = [{"function": "test.py:foo", "count": 100}]
    runtime_file = create_temp_file(json.dumps(runtime_data), ".json")

    try:
        result = run_cli(["risk", diff_file, runtime_file, "report.json"])
        assert isinstance(result, list)  # Should return report list
        assert os.path.exists("report.json")
        os.unlink("report.json")
    finally:
        os.unlink(diff_file)
        os.unlink(runtime_file)


def test_report_command():
    """Test report command."""
    report_data = [
        {
            "function": "test.py:foo",
            "risk": "HIGH",
            "change": "REMOVED",
            "exposure": 0.5,
            "confidence": 0.9,
            "details": "called 100 times",
        }
    ]
    report_file = create_temp_file(json.dumps(report_data), ".json")

    try:
        result = run_cli(["report", report_file, "output.html"])
        assert result == 0
        assert os.path.exists("output.html")
        os.unlink("output.html")
    finally:
        os.unlink(report_file)
