"""Tests for ImpactGuard functionality."""

from __future__ import annotations

import json
import os  
import sys
import tempfile  
from pathlib import Path
from unittest.mock import MagicMock, patch

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

