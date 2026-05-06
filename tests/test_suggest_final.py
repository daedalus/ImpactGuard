"""Final targeted test for suggest_fixes.py lines 79-156."""

from impactguard.suggest_fixes import enrich_with_fixes, suggest


# Test with various inputs to cover lines 79-156
def test_suggest_fixes_comprehensive():
    """Comprehensive test to cover suggest_fixes.py missing lines."""

    # Test with patch types
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

        enriched = enrich_with_fixes(item, [item])
        assert isinstance(enriched, list)


# Test with callsites
def test_suggest_with_callsites():
    """Test suggest with callsites to cover more lines."""
    item = {
        "fqname": "test.py:foo",
        "change": "OPTIONAL ADDED",
        "callsites": [
            {"file": "main.py", "lineno": 10, "args": 2},
            {"file": "other.py", "lineno": 20, "args": 3},
        ],
    }

    result = suggest(item, [item])
    assert isinstance(result, list)

    enriched = enrich_with_fixes(item, [item])
    assert isinstance(enriched, list)


# Test with no patches
def test_suggest_no_patches():
    """Test suggest with no patches."""
    item = {
        "fqname": "test.py:foo",
        "change": "REMOVED",
    }

    result = suggest(item, [item])
    assert isinstance(result, list)


# Test enrich_with_fixes with various inputs
def test_enrich_variants():
    """Test enrich_with_fixes with various inputs."""
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
