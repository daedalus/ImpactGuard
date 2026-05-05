"""Tests for CLI module - fixed."""

import sys
from unittest.mock import patch, mock_open


def run_cli(args):
    """Run CLI with args."""
    from impactguard.__main__ import main
    with patch('sys.argv', ['impactguard'] + args):
        try:
            return main()
        except SystemExit as e:
            return e.code


def test_cli_help(capsys):
    """Test CLI help."""
    result = run_cli(['--help'])
    # Help exits with 0
    assert result == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_cli_version(capsys):
    """Test CLI version."""
    result = run_cli(['--version'])
    # Version exits with 0
    assert result == 0


def test_extract_no_files(capsys):
    """Test extract with no files."""
    from io import StringIO
    from unittest.mock import patch
    with patch('sys.stdin', StringIO('')):
        result = run_cli(['extract'])
    captured = capsys.readouterr()
    assert "no input" in captured.out.lower() or result == 1


def test_cli_no_command(capsys):
    """Test CLI with no command."""
    result = run_cli([])
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower() or result == 1
