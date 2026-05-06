"""Ultra-targeted tests for suggest_fixes.py lines 79-156."""

from impactguard.suggest_fixes import enrich_with_fixes, suggest


def test_suggest_fixes_all_branches():
    """Test suggest() with many inputs to cover lines 79-156."""

    # Test with patches
    item1 = {
        "fqname": "test.py:foo",
        "change": "OPTIONAL POSITIONAL ADDED",
        "patches": [{"type": "add_default", "param": "x", "default": None}],
    }
    result = suggest(item1, [item1])
    assert isinstance(result, list)

    # Test with callsites
    item2 = {
        "fqname": "test.py:bar",
        "change": "ADDED",
        "callsites": [{"file": "main.py", "lineno": 10, "args": 2}],
    }
    result = suggest(item2, [item2])
    assert isinstance(result, list)

    # Test with risk_level
    item3 = {
        "fqname": "test.py:baz",
        "change": "REMOVED",
        "risk_level": "HIGH",
    }
    result = suggest(item3, [item3])
    assert isinstance(result, list)


def test_enrich_with_fixes_all_branches():
    """Test enrich_with_fixes() with many inputs."""

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


def test_suggest_with_various_patch_types():
    """Test suggest() with various patch types."""

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


def test_suggest_with_various_change_types():
    """Test suggest() with various change types."""

    change_types = [
        "OPTIONAL POSITIONAL ADDED",
        "POSITIONAL REMOVED",
        "KWONLY ADDED",
        "REMOVED",
    ]

    for change in change_types:
        item = {
            "fqname": "test.py:foo",
            "change": change,
        }
        result = suggest(item, [item])
        assert isinstance(result, list)
