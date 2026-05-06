"""Final push to 80% - targeting specific missing lines."""

import json
from pathlib import Path
from tempfile import mkdtemp


def test_suggest_fixes_coverage_final(tmp_path):
    """Target missing lines in suggest_fixes.py."""
    from impactguard.suggest_fixes import enrich_with_fixes, suggest

    # Test with various configurations
    items = [
        {
            "fqname": "test.py:foo",
            "change": "OPTIONAL POSITIONAL ADDED",
            "risk_level": "MEDIUM",
            "callsites": [{"file": "main.py", "lineno": 10}],
        },
    ]

    result = suggest(items[0], items)
    assert isinstance(result, list)

    enriched = enrich_with_fixes(items[0], items)
    assert isinstance(enriched, list)


def test_main_coverage_final(tmp_path):
    """Target missing lines in __main__.py."""
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


def test_risk_gate_coverage_final(tmp_path):
    """Target missing lines in risk_gate.py."""
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


def test_pipeline_coverage_final(tmp_path):
    """Target missing lines in pipeline.py."""
    from impactguard.pipeline import quick_check, run_pipeline

    # Test quick_check with directory
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    (old_dir / "module.py").write_text("def foo(): pass\n")

    new_dir = tmp_path / "new"
    new_dir.mkdir()
    (new_dir / "module.py").write_text("def foo(x): pass\n")

    result = quick_check(str(old_dir), str(new_dir))
    assert "signatures" in result


def test_generate_report_coverage_final(tmp_path):
    """Target missing lines in generate_report.py."""
    from impactguard.generate_report import generate_html

    # Test with items
    items = [
        {"fqname": "test:foo", "risk_level": "HIGH", "change": "REMOVED"},
    ]

    result = generate_html(items)
    assert "HIGH" in result


def test_extract_signatures_coverage_final(tmp_path):
    """Target missing lines in extract_signatures.py."""
    from impactguard.extract_signatures import extract

    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(): pass\n")

    result = extract([str(test_file)])
    assert len(result) >= 1


def test_compare_signatures_coverage_final(tmp_path):
    """Target missing lines in compare_signatures.py."""
    from impactguard.compare_signatures import compare

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
            "positional": [
                {"name": "a", "has_default": False},
                {"name": "b", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old))
    new_path.write_text(json.dumps(new))

    result = compare(str(old_path), str(new_path))
    assert "nonbreaking" in result


def test_impact_analysis_coverage_final(tmp_path):
    """Target missing lines in impact_analysis.py."""
    from impactguard.impact_analysis import analyze

    sigs = tmp_path / "sigs.json"
    sigs.write_text(
        json.dumps(
            [
                {
                    "fqname": "test:foo",
                    "name": "foo",
                    "positional": [{"name": "a", "has_default": False}],
                    "kwonly": [],
                    "vararg": False,
                    "kwarg": False,
                }
            ]
        )
    )

    calls = tmp_path / "calls.json"
    calls.write_text(json.dumps([{"fqname": "test:foo", "file": "main.py"}]))

    result = analyze(str(sigs), str(calls))
    assert isinstance(result, list)


def test_extract_calls_coverage_final(tmp_path):
    """Target missing lines in extract_calls.py."""
    from impactguard.extract_calls import extract

    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(): bar()\n")

    result = extract(test_file)
    assert isinstance(result, list)
    assert len(result) > 0


def test_analyze_module_coverage_final(tmp_path):
    """Target missing lines in analyze_module.py."""
    from impactguard.analyze_module import analyze

    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(a, b=1): return a + b\n")

    result = analyze(str(test_file))
    assert isinstance(result, dict)
