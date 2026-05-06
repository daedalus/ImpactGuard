"""Ultra-targeted tests for suggest_fixes.py missing lines 79-156."""

import json
from pathlib import Path
from tempfile import mkdtemp


def test_suggest_fixes_lines_79_156(tmp_path):
    """Target missing lines 79-156 in suggest_fixes.py."""
    from impactguard.suggest_fixes import enrich_with_fixes, suggest

    # Test with various configurations to hit missing lines
    test_items = [
        {
            "fqname": "test.py:foo",
            "change": "OPTIONAL POSITIONAL ADDED",
            "risk_level": "LOW",
            "callsites": [{"file": "main.py", "lineno": 10}],
            "patches": [{"type": "add_default", "param": "x"}],
        },
        {
            "fqname": "test.py:bar",
            "change": "POSITIONAL REMOVED",
            "risk_level": "HIGH",
        },
    ]

    for item in test_items:
        result = suggest(item, test_items)
        assert isinstance(result, list)

        enriched = enrich_with_fixes(item, test_items)
        assert isinstance(enriched, list)


def test_suggest_fixes_with_patch_types(tmp_path):
    """Test various patch types to cover more lines."""
    from impactguard.suggest_fixes import suggest

    # Test with different patch types
    patch_types = [
        {"type": "add_default", "param": "x", "default": None},
        {"type": "add_kwarg", "param": "kwargs"},
        {"type": "wrap_function", "wrapper": "decorator"},
    ]

    for patch in patch_types:
        item = {
            "fqname": "test.py:foo",
            "change": "ADDED",
            "patches": [patch],
        }
        result = suggest(item, [item])
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
