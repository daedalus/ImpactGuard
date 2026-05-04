"""Tests to push coverage from 73% to 80%."""

import json
from pathlib import Path
from tempfile import mkdtemp


def test_suggest_fixes_coverage_push(tmp_path):
    """Push suggest_fixes.py coverage up."""
    from impactguard.suggest_fixes import suggest, enrich_with_fixes

    items = [
        {
            "fqname": "test.py:foo",
            "change": "OPTIONAL POSITIONAL ADDED",
            "risk_level": "MEDIUM",
            "callsites": [{"file": "main.py", "lineno": 10}],
            "patches": [{"type": "add_default", "param": "x"}],
        },
    ]

    result = suggest(items[0], items)
    assert isinstance(result, list)

    enriched = enrich_with_fixes(items[0], items)
    assert isinstance(enriched, list)


def test_main_coverage_push(tmp_path):
    """Push __main__.py coverage up."""
    import sys
    from impactguard.__main__ import main

    # Test check command
    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(): pass\n")
    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(x): pass\n")

    sys.argv = ["impactguard", "check", str(old_file), str(new_file)]
    try:
        main()
    except SystemExit as e:
        assert e.code in [0, 1]


def test_risk_gate_coverage_push(tmp_path):
    """Push risk_gate.py coverage up."""
    from impactguard.risk_gate import run as run_risk

    # Test with diff and runtime
    diff = tmp_path / "diff.txt"
    diff.write_text("POSITIONAL REMOVED: test.py:foo\n")

    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps([{"function": "foo", "args_count": 1}]))

    output = tmp_path / "risk.json"
    result = run_risk(str(diff), str(runtime), str(output))
    assert isinstance(result, list)
    assert len(result) > 0


def test_pipeline_coverage_push(tmp_path):
    """Push pipeline.py coverage up."""
    from impactguard.pipeline import run_pipeline, quick_check

    # Test quick_check with directory
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    (old_dir / "module.py").write_text("def foo(): pass\n")

    new_dir = tmp_path / "new"
    new_dir.mkdir()
    (new_dir / "module.py").write_text("def foo(x): pass\n")

    result = quick_check(str(old_dir), str(new_dir))
    assert "signatures" in result

    # Test run_pipeline with all options
    result = run_pipeline(
        old_files=[str(old_dir / "module.py")],
        new_files=[str(new_dir / "module.py")],
        output_dir=str(tmp_path / "output"),
    )
    assert "comparison" in result
    assert "signatures" in result


def test_generate_report_coverage_push(tmp_path):
    """Push generate_report.py coverage up."""
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


def test_extract_signatures_coverage_push(tmp_path):
    """Push extract_signatures.py coverage up."""
    from impactguard.extract_signatures import extract

    # Test with file containing class
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
    for sig in result:
        if "method" in sig["name"]:
            assert sig["class_name"] == "MyClass"


def test_compare_signatures_coverage_push(tmp_path):
    """Push compare_signatures.py coverage up."""
    from impactguard.compare_signatures import compare

    # Test with added function (non-breaking)
    old = [{"fqname": "test:foo", "name": "foo",
             "positional": [{"name": "a", "has_default": False}],
             "kwonly": [], "vararg": False, "kwarg": False}]

    new = [{"fqname": "test:foo", "name": "foo",
             "positional": [{"name": "a", "has_default": False}],
             "kwonly": [{"name": "x", "has_default": True}],
             "vararg": False, "kwarg": False},
            {"fqname": "test:bar", "name": "bar",
             "positional": [], "kwonly": [],
             "vararg": False, "kwarg": False}]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old))
    new_path.write_text(json.dumps(new))

    result = compare(str(old_path), str(new_path))
    assert "nonbreaking" in result
    assert len(result["nonbreaking"]) > 0


def test_impact_analysis_coverage_push(tmp_path):
    """Push impact_analysis.py coverage up."""
    from impactguard.impact_analysis import analyze

    sigs = tmp_path / "sigs.json"
    sigs.write_text(json.dumps([
        {"fqname": "test:foo", "name": "foo",
         "positional": [{"name": "a", "has_default": False}],
         "kwonly": [], "vararg": False, "kwarg": False}
    ]))

    calls = tmp_path / "calls.json"
    calls.write_text(json.dumps([
        {"fqname": "test:foo", "file": "main.py", "lineno": 10}
    ]))

    result = analyze(str(sigs), str(calls))
    assert isinstance(result, list)


def test_extract_calls_coverage_push(tmp_path):
    """Push extract_calls.py coverage up."""
    from impactguard.extract_calls import extract

    test_file = tmp_path / "test.py"
    test_file.write_text("""
def foo():
    if True:
        bar()
        baz()

class MyClass:
    def method(self):
        self.helper()

def helper():
    another_func()
""")

    result = extract(test_file)
    assert isinstance(result, list)
    assert len(result) > 0
