"""Targeted tests for low coverage modules."""

import json
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch, MagicMock


def test_suggest_fixes_all_paths(tmp_path):
    """Test suggest_fixes module - cover all paths."""
    from impactguard.suggest_fixes import suggest, enrich_with_fixes

    # Test with patches
    item_with_patch = {
        "fqname": "test.py:foo",
        "change": "OPTIONAL POSITIONAL ADDED",
        "patches": [{"type": "add_default", "param": "x"}],
    }
    result = suggest(item_with_patch, [item_with_patch])
    assert isinstance(result, list)

    # Test with callsites
    item_with_calls = {
        "fqname": "test.py:bar",
        "change": "ADDED",
        "callsites": [{"file": "main.py", "lineno": 10}],
    }
    result = suggest(item_with_calls, [item_with_calls])
    assert isinstance(result, list)

    # Test enrich_with_fixes
    enriched = enrich_with_fixes(item_with_patch, [item_with_patch])
    assert isinstance(enriched, list)


def test_main_all_commands(tmp_path):
    """Test __main__.py - cover all commands."""
    import sys
    from impactguard.__main__ import main

    # Test extract command
    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(): pass\n")

    sys.argv = ["impactguard", "extract", str(test_file)]
    try:
        main()
    except SystemExit as e:
        assert e.code == 0

    # Test compare command
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps([{"fqname": "test:foo", "name": "foo",
                                     "positional": [], "kwonly": [],
                                     "vararg": False, "kwarg": False}]))
    new_path.write_text(json.dumps([{"fqname": "test:foo", "name": "foo",
                                     "positional": [{"name": "a", "has_default": True}],
                                     "kwonly": [], "vararg": False, "kwarg": False}]))

    sys.argv = ["impactguard", "compare", str(old_path), str(new_path)]
    try:
        main()
    except SystemExit as e:
        assert e.code == 0

    # Test enforce command
    diff_path = tmp_path / "diff.txt"
    diff_path.write_text("")
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text("[]")

    sys.argv = ["impactguard", "enforce", str(diff_path), str(runtime_path)]
    try:
        main()
    except SystemExit as e:
        assert e.code == 0


def test_risk_gate_all_paths(tmp_path):
    """Test risk_gate module - cover all paths."""
    from impactguard.risk_gate import run as run_risk

    # Test with empty diff
    empty_diff = tmp_path / "empty.txt"
    empty_diff.write_text("")
    result = run_risk(str(empty_diff), "", str(tmp_path / "out.json"))
    assert isinstance(result, list)

    # Test with diff and runtime data
    diff = tmp_path / "diff.txt"
    diff.write_text("POSITIONAL REMOVED: test.py:foo\n")

    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps([{"function": "foo", "args_count": 1}]))

    result = run_risk(str(diff), str(runtime), str(tmp_path / "out2.json"))
    assert isinstance(result, list)
    assert len(result) > 0
    # Risk could be HIGH or UNKNOWN depending on runtime data
    assert result[0]["risk"] in ["HIGH", "UNKNOWN"]


def test_pipeline_all_paths(tmp_path):
    """Test pipeline module - cover more paths."""
    from impactguard.pipeline import run_pipeline, quick_check

    # Test with old_files and new_files
    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a): return a\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b=1): return a + b\n")

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        output_dir=str(tmp_path / "output"),
    )
    assert "comparison" in result
    assert "signatures" in result

    # Test quick_check with directory
    old_dir = tmp_path / "old_dir"
    old_dir.mkdir()
    (old_dir / "module.py").write_text("def foo(): pass\n")

    new_dir = tmp_path / "new_dir"
    new_dir.mkdir()
    (new_dir / "module.py").write_text("def foo(x): pass\n")

    result = quick_check(str(old_dir), str(new_dir))
    assert "signatures" in result


def test_generate_report_all(tmp_path):
    """Test generate_report module - cover more paths."""
    from impactguard.generate_report import generate_html

    # Test with empty list
    result = generate_html([])
    assert isinstance(result, str)

    # Test with items
    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
        {"fqname": "test:bar", "risk_level": "LOW", "change": "ADDED"},
    ]
    result = generate_html(items)
    assert "HIGH" in result
    assert "LOW" in result


def test_extract_signatures_all(tmp_path):
    """Test extract_signatures - cover more paths."""
    from impactguard.extract_signatures import extract

    # Test with file that has class
    test_file = tmp_path / "test.py"
    test_file.write_text("""
def top_level():
    pass

class MyClass:
    def method(self):
        pass
""")

    result = extract([str(test_file)])
    assert len(result) >= 2

    # Check class context
    method_sigs = [s for s in result if "MyClass" in s.get("name", "")]
    assert len(method_sigs) > 0


def test_compare_signatures_all(tmp_path):
    """Test compare_signatures - cover more paths."""
    from impactguard.compare_signatures import compare

    # Test with kwonly changes
    old = [{"fqname": "test:foo", "name": "foo",
            "positional": [],
            "kwonly": [],
            "vararg": False, "kwarg": False}]

    new = [{"fqname": "test:foo", "name": "foo",
            "positional": [],
            "kwonly": [{"name": "x", "has_default": True}],
            "vararg": False, "kwarg": False}]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old))
    new_path.write_text(json.dumps(new))

    result = compare(str(old_path), str(new_path))
    assert "nonbreaking" in result
    assert len(result["nonbreaking"]) > 0
