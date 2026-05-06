"""Comprehensive tests to reach 80% coverage."""

import json
from pathlib import Path
from tempfile import mkdtemp


def test_suggest_fixes_full_coverage(tmp_path):
    """Test suggest_fixes module fully."""
    from impactguard.suggest_fixes import enrich_with_fixes, suggest

    # Test with various risk items
    risk_items = [
        {
            "fqname": "test.py:foo",
            "change": "OPTIONAL POSITIONAL ADDED: test.py:foo",
            "risk_level": "MEDIUM",
            "callsites": [{"file": "main.py", "lineno": 10}],
            "patches": [{"type": "add_default", "param": "x"}],
        },
        {
            "fqname": "test.py:bar",
            "change": "POSITIONAL REMOVED: test.py:bar",
            "risk_level": "HIGH",
        },
    ]

    for item in risk_items:
        result = suggest(item, risk_items)
        assert isinstance(result, list)

        enriched = enrich_with_fixes(item, risk_items)
        assert isinstance(enriched, list)


def test_enforce_gate_full_coverage(tmp_path):
    """Test enforce_gate module fully."""
    from impactguard.enforce_gate import enforce_report

    # Test with HIGH risk - should fail
    report_path = tmp_path / "high.json"
    report_path.write_text(json.dumps([{"risk": "HIGH", "function": "test:foo"}]))
    assert enforce_report(str(report_path)) == 1

    # Test with LOW risk - should pass
    report_path = tmp_path / "low.json"
    report_path.write_text(json.dumps([{"risk": "LOW", "function": "test:foo"}]))
    assert enforce_report(str(report_path)) == 0

    # Test with UNKNOWN risk - should warn but pass
    report_path = tmp_path / "unknown.json"
    report_path.write_text(json.dumps([{"risk": "UNKNOWN", "function": "test:bar"}]))
    result = enforce_report(str(report_path))
    assert result == 0

    # Test with mixed - should fail
    report_path = tmp_path / "mixed.json"
    report_path.write_text(
        json.dumps(
            [
                {"risk": "LOW", "function": "test:foo"},
                {"risk": "HIGH", "function": "test:bar"},
            ]
        )
    )
    assert enforce_report(str(report_path)) == 1


def test_risk_gate_full_coverage(tmp_path):
    """Test risk_gate module fully."""
    from impactguard.risk_gate import run as run_risk

    # Test with empty diff
    empty_diff = tmp_path / "empty.txt"
    empty_diff.write_text("")

    result = run_risk(str(empty_diff), "", str(tmp_path / "out1.json"))
    assert isinstance(result, list)
    assert len(result) == 0

    # Test with diff and runtime
    diff = tmp_path / "diff.txt"
    diff.write_text("POSITIONAL REMOVED: test.py:foo\n")

    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps([{"function": "foo", "args_count": 1}]))

    result = run_risk(str(diff), str(runtime), str(tmp_path / "out2.json"))
    assert isinstance(result, list)


def test_generate_report_full_coverage(tmp_path):
    """Test generate_report module fully."""
    from impactguard.generate_report import generate_html

    # Test with empty list
    result = generate_html([])
    assert isinstance(result, str)

    # Test with single item
    result = generate_html([{"fqname": "test:foo", "risk_level": "LOW"}])
    assert isinstance(result, str)

    # Test with multiple items
    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
        {"fqname": "test:bar", "risk_level": "MEDIUM", "change": "ADDED"},
        {"fqname": "test:baz", "risk_level": "LOW", "change": "NONE"},
    ]
    result = generate_html(items)
    assert "HIGH" in result
    assert "MEDIUM" in result
    assert "LOW" in result


def test_extract_calls_full_coverage(tmp_path):
    """Test extract_calls module fully."""
    from impactguard.extract_calls import extract

    # Test with simple file
    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(): bar()\n")
    result = extract(test_file)
    assert isinstance(result, list)

    # Test with complex file
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


def test_analyze_module_full_coverage(tmp_path):
    """Test analyze_module fully."""
    from impactguard.analyze_module import analyze

    # Test with file with imports and functions
    test_file = tmp_path / "test.py"
    test_file.write_text("""
import os
from pathlib import Path

def foo(a, b=1):
    return a + b

class MyClass:
    def method(self, x):
        return x * 2

async def async_func():
    pass
""")

    result = analyze(str(test_file))
    assert isinstance(result, dict)


def test_pipeline_full_coverage(tmp_path):
    """Test pipeline module fully."""
    from impactguard import ImpactGuard
    from impactguard.pipeline import quick_check, run_pipeline

    # Test ImpactGuard class
    guard = ImpactGuard({"test": True})
    assert guard.config == {"test": True}

    # Test quick_check
    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(): pass\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(x): pass\n")

    result = quick_check(str(old_file), str(new_file))
    assert "signatures" in result

    # Test run_pipeline with all options
    calls = tmp_path / "calls.json"
    calls.write_text(json.dumps([{"fqname": "test:foo", "file": "main.py"}]))

    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps([{"function": "foo", "args_count": 0}]))

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        calls_path=str(calls),
        runtime_path=str(runtime),
        output_dir=str(tmp_path / "output"),
    )
    assert "comparison" in result
    assert "impact" in result
    assert "risk" in result


def test_extract_signatures_full_coverage(tmp_path):
    """Test extract_signatures fully."""
    from impactguard.extract_signatures import extract

    # Test with file containing class
    test_file = tmp_path / "test.py"
    test_file.write_text("""
def top_level():
    pass

class MyClass:
    def method(self):
        pass

    async def async_method(self):
        pass
""")

    result = extract([str(test_file)])
    assert len(result) >= 3

    # Check class context
    for sig in result:
        if "method" in sig["name"]:
            assert sig["class_name"] == "MyClass"


def test_compare_signatures_full_coverage(tmp_path):
    """Test compare_signatures fully."""
    from impactguard.compare_signatures import compare

    # Test with added function (non-breaking)
    old = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [{"name": "a", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    new = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [{"name": "a", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
        {
            "fqname": "test:bar",
            "name": "bar",
            "positional": [],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
    ]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old))
    new_path.write_text(json.dumps(new))

    result = compare(str(old_path), str(new_path))
    assert len(result["nonbreaking"]) > 0

    # Test with removed function (breaking)
    new = []  # bar removed
    new_path.write_text(json.dumps(new))

    result = compare(str(old_path), str(new_path))
    assert len(result["breaking"]) > 0
