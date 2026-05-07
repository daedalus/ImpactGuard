"""Additional tests for coverage boost."""

import json
from pathlib import Path
from tempfile import mkdtemp


def test_suggest_fixes_with_cst_patch(tmp_path):
    """Test suggest_fixes with CST patch available."""
    from impactguard.suggest_fixes import suggest

    risk_item = {
        "fqname": "test.py:foo",
        "change": "POSITIONAL_REMOVED: test.py:foo",
        "patches": [{"type": "add_default", "param": "x", "default": "None"}],
    }

    result = suggest(risk_item, [risk_item])
    assert isinstance(result, list)


def test_suggest_fixes_with_call_sites(tmp_path):
    """Test suggest_fixes with call sites."""
    from impactguard.suggest_fixes import suggest

    risk_item = {
        "fqname": "test.py:foo",
        "change": "OPTIONAL_POSITIONAL_ADDED: test.py:foo",
        "callsites": [{"file": "main.py", "lineno": 10, "args": 2}],
    }

    result = suggest(risk_item, [risk_item])
    assert isinstance(result, list)


def test_enrich_with_fixes_basic(tmp_path):
    """Test enrich_with_fixes basic functionality."""
    from impactguard.suggest_fixes import enrich_with_fixes

    risk_item = {
        "fqname": "test.py:foo",
        "risk_level": "MEDIUM",
    }

    result = enrich_with_fixes(risk_item, [risk_item])
    assert isinstance(result, list)


def test_run_pipeline_with_calls_path(tmp_path):
    """Test run_pipeline with provided calls_path."""
    from impactguard.pipeline import run_pipeline

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a): return a\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b=1): return a + b\n")

    calls_data = [{"fqname": "test.py:foo", "file": "main.py", "lineno": 5}]
    calls_path = tmp_path / "calls.json"
    calls_path.write_text(json.dumps(calls_data))

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        calls_path=str(calls_path),
        output_dir=str(tmp_path / "output"),
    )

    assert "impact" in result


def test_run_pipeline_with_runtime_path(tmp_path):
    """Test run_pipeline with runtime data."""
    from impactguard.pipeline import run_pipeline

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a): return a\n")

    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b=1): return a + b\n")

    runtime_data = [{"function": "foo", "args_count": 1, "kwargs": []}]
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps(runtime_data))

    result = run_pipeline(
        old_files=[str(old_file)],
        new_files=[str(new_file)],
        runtime_path=str(runtime_path),
        output_dir=str(tmp_path / "output"),
    )

    assert "risk" in result


def test_impact_analysis_import():
    """Test impact_analysis import."""
    from impactguard.impact_analysis import analyze

    assert callable(analyze)


def test_impact_analysis_basic(tmp_path):
    """Test impact_analysis with basic input."""
    from impactguard.impact_analysis import analyze

    sigs_path = tmp_path / "sigs.json"
    sigs_path.write_text(json.dumps([]))

    calls_path = tmp_path / "calls.json"
    calls_path.write_text(json.dumps([]))

    result = analyze(str(sigs_path), str(calls_path))
    assert isinstance(result, list)


def test_risk_gate_import():
    """Test risk_gate import."""
    from impactguard.risk_gate import run as run_risk

    assert callable(run_risk)


def test_risk_gate_basic(tmp_path):
    """Test risk_gate with basic input."""
    from impactguard.risk_gate import run as run_risk

    diff_path = tmp_path / "diff.txt"
    diff_path.write_text("POSITIONAL_REMOVED: test.py:foo\n")

    output_path = tmp_path / "risk.json"

    result = run_risk(str(diff_path), "", str(output_path))
    assert isinstance(result, list)


def test_compare_signatures_edge_cases(tmp_path):
    """Test compare_signatures edge cases."""
    from impactguard.compare_signatures import compare

    # Same signatures - no changes
    sigs = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [{"name": "a", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(sigs))
    new_path.write_text(json.dumps(sigs))

    result = compare(str(old_path), str(new_path))
    assert len(result["breaking"]) == 0
    assert len(result["nonbreaking"]) == 0


def test_compare_with_vararg_changes(tmp_path):
    """Test compare with *args changes."""
    from impactguard.compare_signatures import compare

    old = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [{"name": "a", "has_default": False}],
            "kwonly": [],
            "vararg": True,
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
        }
    ]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old))
    new_path.write_text(json.dumps(new))

    result = compare(str(old_path), str(new_path))
    assert len(result["breaking"]) > 0
    assert any("*args" in c for c in result["breaking"])
