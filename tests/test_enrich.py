"""Tests for ImpactGuard functionality."""

from __future__ import annotations

import json
import os  
import sys
import tempfile  
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_enrich_with_fixes_basic(tmp_path):
    """Test enrich_with_fixes basic functionality."""
    from impactguard.suggest_fixes import enrich_with_fixes

    risk_item = {
        "fqname": "test.py:foo",
        "risk_level": "MEDIUM",
    }

    result = enrich_with_fixes(risk_item, [risk_item])
    assert isinstance(result, list)

def test_enrich_variants():
    """Test enrich_with_fixes with various inputs."""
    from impactguard.suggest_fixes import enrich_with_fixes

    # With patches
    item1 = {
        "fqname": "test.py:foo",
        "patches": [{"type": "add_default"}],
    }
    result = enrich_with_fixes(item1, [item1])
    assert isinstance(result, list)

    # With callsites
    item2 = {
        "fqname": "test.py:bar",
        "callsites": [{"file": "main.py"}],
    }
    result = enrich_with_fixes(item2, [item2])
    assert isinstance(result, list)

# =======================================

def test_enrich_with_fixes_all_branches():
    """Test enrich_with_fixes() with many inputs."""
    from impactguard.suggest_fixes import enrich_with_fixes

    # Test with patches
    item1 = {
        "fqname": "test.py:foo",
        "patches": [{"type": "add_default"}],
    }
    result = enrich_with_fixes(item1, [item1])
    assert isinstance(result, list)

    # Test with callsites
    item2 = {
        "fqname": "test.py:bar",
        "callsites": [{"file": "main.py"}],
    }
    result = enrich_with_fixes(item2, [item2])
    assert isinstance(result, list)

    # Test with no patches or callsites
    item3 = {
        "fqname": "test.py:baz",
    }
    result = enrich_with_fixes(item3, [item3])
    assert isinstance(result, list)

def test_enrich_with_fixes_variants(tmp_path):
    """Test enrich_with_fixes with various inputs."""
    from impactguard.suggest_fixes import enrich_with_fixes

    # Test with item that has patches
    item_with_patch = {
        "fqname": "test.py:foo",
        "patches": [{"type": "add_default"}],
    }
    enriched = enrich_with_fixes(item_with_patch, [item_with_patch])
    assert isinstance(enriched, list)

    # Test with item that has callsites
    item_with_calls = {
        "fqname": "test.py:bar",
        "callsites": [{"file": "main.py"}],
    }
    enriched = enrich_with_fixes(item_with_calls, [item_with_calls])
    assert isinstance(enriched, list)

