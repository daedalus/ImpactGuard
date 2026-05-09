"""Tests for ImpactGuard functionality."""

from __future__ import annotations

import json
import os  
import sys
import tempfile  
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_runtime_impact_if_available(tmp_path):
    """Test runtime_impact if available."""
    try:
        from impactguard.runtime_impact import analyze

        sigs = [{"fqname": "test:foo", "name": "foo"}]
        calls = [{"fqname": "test:foo", "file": "main.py"}]

        result = analyze(sigs, calls)
        assert isinstance(result, list)

    except ImportError:
        pass

