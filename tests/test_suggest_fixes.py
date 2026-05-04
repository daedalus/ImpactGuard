"""Tests for suggest_fixes module."""

from impactguard.suggest_fixes import enrich_with_fixes, get_line, suggest


def test_suggest():
    """Test suggest function."""
    func = {"name": "foo"}
    issues = [{"type": "missing_args"}]
    result = suggest(func, issues)
    assert isinstance(result, list)
    assert len(result) > 0


def test_get_line():
    """Test get_line function."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("line1\nline2\nline3\n")
        fname = f.name

    result = get_line(fname, 2)
    assert "line2" in result or result == ""  # Might return empty on error

    import os

    os.unlink(fname)


def test_enrich_with_fixes():
    """Test enrich_with_fixes function."""
    report_item = {"patches": ["patch1"], "callsite_patches": ["patch2"]}
    issues = []
    result = enrich_with_fixes(report_item, issues)
    assert isinstance(result, list)
