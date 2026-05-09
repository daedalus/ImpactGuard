"""Tests for ImpactGuard functionality."""

from __future__ import annotations

import json
import os  
import sys
import tempfile  
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_cst_patch_if_available(tmp_path):
    """Test cst_patch if libcst is available."""
    try:
        from impactguard.cst_patch import generate_patch

        old_code = "def foo(a, b): pass\n"
        new_code = "def foo(a, b, c=0): pass\n"

        # Test generate_patch
        patch = generate_patch(old_code, new_code)
        assert isinstance(patch, (str, dict))

    except ImportError:
        pass  # libcst not installed

