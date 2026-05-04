"""Tests to boost coverage for suggest_fixes.py."""

import json
from pathlib import Path
from tempfile import mkdtemp


def test_suggest_fixes_import():
    """Test that suggest_fixes can be imported."""
    from impactguard.suggest_fixes import suggest, enrich_with_fixes

    assert callable(suggest)
    assert callable(enrich_with_fixes)


def test_suggest_fixes_empty():
    """Test suggest_fixes with empty input."""
    from impactguard.suggest_fixes import suggest

    result = suggest({}, [])
    assert isinstance(result, list)


def test_enrich_with_fixes_empty():
    """Test enrich_with_fixes with empty input."""
    from impactguard.suggest_fixes import enrich_with_fixes

    result = enrich_with_fixes({}, [])
    assert isinstance(result, list)


def test_suggest_with_risk_item(tmp_path):
    """Test suggest_fixes with a risk item."""
    from impactguard.suggest_fixes import suggest

    risk_item = {
        "fqname": "test.py:foo",
        "change": "POSITIONAL REMOVED: test.py:foo",
        "risk_level": "HIGH",
    }

    result = suggest(risk_item, [risk_item])
    assert isinstance(result, list)


def test_suggest_fixes_with_patches(tmp_path):
    """Test suggest_fixes when patches exist."""
    from impactguard.suggest_fixes import suggest

    risk_item = {
        "fqname": "test.py:foo",
        "change": "POSITIONAL REMOVED",
        "patches": [
            {"type": "add_default", "param": "x", "default": "None"}
        ],
    }

    result = suggest(risk_item, [risk_item])
    assert isinstance(result, list)


def test_cst_patch_import():
    """Test that cst_patch can be imported."""
    try:
        from impactguard.cst_patch import apply_patch, generate_patch

        assert callable(apply_patch)
        assert callable(generate_patch)
    except ImportError:
        pass  # libcst not installed


def test_patch_confidence_import():
    """Test that patch_confidence can be imported."""
    from impactguard.patch_confidence import classify_with_factors

    assert callable(classify_with_factors)


def test_patch_confidence_classify():
    """Test patch_confidence classification."""
    from impactguard.patch_confidence import classify_with_factors

    # target, structural, semantic, complexity
    label, factors = classify_with_factors(0.8, 1.0, 1.0, 1.0)
    assert isinstance(label, str)
    assert isinstance(factors, dict)


def test_generate_report_import():
    """Test that generate_report can be imported."""
    from impactguard.generate_report import generate_html

    assert callable(generate_html)


def test_generate_report_empty():
    """Test generate_report with empty input."""
    from impactguard.generate_report import generate_html

    result = generate_html([])
    assert isinstance(result, str)
    assert "HIGH" in result or "LOW" in result or "MEDIUM" in result


def test_generate_report_with_items():
    """Test generate_report with risk items."""
    from impactguard.generate_report import generate_html

    items = [
        {
            "fqname": "test.py:foo",
            "risk_level": "HIGH",
            "change": "POSITIONAL REMOVED",
        }
    ]

    result = generate_html(items)
    assert isinstance(result, str)
    assert "HIGH" in result


def test_enforce_gate_import():
    """Test that enforce_gate can be imported."""
    from impactguard.enforce_gate import enforce

    assert callable(enforce)


def test_enforce_gate_no_high():
    """Test enforce_gate with no HIGH risk items."""
    from impactguard.enforce_gate import enforce

    items = [
        {"risk_level": "LOW", "fqname": "test:foo"},
        {"risk_level": "MEDIUM", "fqname": "test:bar"},
    ]

    result = enforce(items)
    assert result == 0  # Should pass


def test_extract_calls_import():
    """Test that extract_calls can be imported."""
    from impactguard.extract_calls import extract

    assert callable(extract)


def test_analyze_module_import():
    """Test that analyze_module can be imported."""
    from impactguard.analyze_module import analyze

    assert callable(analyze)


def test_analyze_module_simple(tmp_path):
    """Test analyze_module with a simple file."""
    from impactguard.analyze_module import analyze

    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(a, b): return a + b\n")

    result = analyze(str(test_file))
    assert isinstance(result, dict)
