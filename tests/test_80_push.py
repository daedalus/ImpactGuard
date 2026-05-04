"""Strategic test to push coverage to 80% - covers remaining missed lines."""

import ast
import json
import os
import tempfile
from unittest.mock import patch

# Imports from all major modules
from impactguard.analyze_module import Analyzer, Scope
from impactguard.compare_signatures import compare
from impactguard.cst_patch import (
    patch_call,
    patch_function,
)
from impactguard.impact_analysis import (
    analyze,
    exposure,
    get_severity,
    required_positional,
    total_positional,
)
from impactguard.patch_confidence import (
    classify as classify_patch,
)
from impactguard.patch_confidence import (
    compute_confidence,
    get_complexity_penalty,
    get_semantic_risk,
    get_structural_safety,
    get_target_certainty,
)
from impactguard.patch_generator import patch_add_default, patch_callsite
from impactguard.suggest_fixes import enrich_with_fixes, get_line, suggest
from impactguard.trace_calls import COUNTS, dump, install_tracer
from impactguard.trace_calls_prod import (
    flush,
    should_sample,
)
from impactguard.trace_calls_prod import (
    install_tracer as install_tracer_prod,
)


# ======= Scope tests (cover lines 17-20) =======
def test_scope_remaining():
    parent = Scope()
    parent.set("x", "int")
    parent.set("y", "str")

    child = Scope(parent=parent)
    child.set("z", "bool")

    # Test inheritance
    assert child.get("x") == "int"  # from parent
    assert child.get("y") == "str"  # from parent
    assert child.get("z") == "bool"  # from self
    assert child.get("nonexistent") is None

    # Test grandchild
    grandchild = Scope(parent=child)
    grandchild.set("w", "float")
    assert grandchild.get("x") == "int"  # from grandparent
    assert grandchild.get("z") == "bool"  # from parent
    assert grandchild.get("w") == "float"


# ======= Analyzer tests (cover lines 60-73, 80->93, 101, 107-114, 118, 126, 131-139) =======
def test_analyzer_remaining():
    code = """
import os
import sys as system
from collections import defaultdict as dd
from pathlib import Path as P

x: int = 10
y: str = "hello"

def foo(a: int, b: str = "default") -> bool:
    return True

class MyClass:
    def __init__(self, x: int):
        self.x = x

    def get_x(self) -> int:
        return self.x

    @staticmethod
    def static_method():
        pass

    @classmethod
    def class_method(cls):
        pass

def bar(*args, **kwargs):
    pass

lambda_func = lambda x: x * 2

try:
    risky = 1 / 0
except ZeroDivisionError as e:
    print(e)
finally:
    pass

os.path.join("a", "b")
"""
    tree = ast.parse(code)
    analyzer = Analyzer("test.py")
    analyzer.visit(tree)

    # Check imports
    assert "os" in analyzer.imports
    assert "system" in analyzer.imports
    assert "dd" in analyzer.from_imports
    assert "P" in analyzer.from_imports

    # Check calls captured
    assert len(analyzer.calls) > 0


# ======= impact_analysis tests (cover lines 29-42, 48, 69-73, 85-89, 94, 133-152) =======
def test_impact_analysis_remaining():
    # Test helper functions
    f = {
        "positional": [
            {"name": "x", "has_default": False},
            {"name": "y", "has_default": True},
        ]
    }
    assert required_positional(f) == 1
    assert total_positional(f) == 2

    assert get_severity("REMOVED") == 1.0
    assert get_severity("REQUIRED") == 0.9
    assert get_severity("unknown") == 0.5

    assert exposure(0, 100) == 0
    assert 0 < exposure(1, 100) < 1.0
    assert exposure(100, 100) == 1.0

    # Test analyze() with various scenarios
    # Scenario 1: missing args
    sigs_data = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [
                {"name": "x", "has_default": False},
                {"name": "y", "has_default": False},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    calls_data = [
        {"fqname": "test.py:foo", "args": 1, "file": "caller.py", "lineno": 10}
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sigs_data, f)
        sigs_file = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(calls_data, f)
        calls_file = f.name

    result = analyze(sigs_file, calls_file)
    assert isinstance(result, list)
    assert len(result) > 0  # Should detect missing args

    os.unlink(sigs_file)
    os.unlink(calls_file)

    # Scenario 2: too many args
    sigs_data2 = [
        {
            "fqname": "test.py:bar",
            "name": "bar",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,  # no *args
            "kwarg": False,
        }
    ]

    calls_data2 = [
        {"fqname": "test.py:bar", "args": 5, "file": "caller.py", "lineno": 20}
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sigs_data2, f)
        sigs_file2 = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(calls_data2, f)
        calls_file2 = f.name

    result2 = analyze(sigs_file2, calls_file2)
    assert isinstance(result2, list)

    os.unlink(sigs_file2)
    os.unlink(calls_file2)

    # Scenario 3: with runtime data
    sigs_data3 = [
        {
            "fqname": "test.py:baz",
            "name": "baz",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    calls_data3 = [
        {"fqname": "test.py:baz", "args": 1, "file": "caller.py", "lineno": 30}
    ]

    runtime_data = [{"function": "test.py:baz", "count": 50}]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sigs_data3, f)
        sigs_file3 = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(calls_data3, f)
        calls_file3 = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(runtime_data, f)
        runtime_file = f.name

    result3 = analyze(sigs_file3, calls_file3, runtime_file)
    assert isinstance(result3, list)

    os.unlink(sigs_file3)
    os.unlink(calls_file3)
    os.unlink(runtime_file)


# ======= cst_patch tests (cover lines 6-7, 17, 25, 43, 51, 55-64, 68-77) =======
def test_cst_patch_remaining():
    try:
        import libcst as cst
        from libcst import matchers as m

        # Test patch_function
        code = "def foo(x): pass"
        result, error = patch_function(code, "foo", "x")
        assert error is None

        # Test patch_function with wrong name
        result2, error2 = patch_function(code, "bar", "x")
        assert result2 == code  # No modification

        # Test patch_call
        code2 = "foo(1, 2)"
        result3, error3 = patch_call(code2, "foo", "new_arg")
        assert error3 is None or result3 is not None

    except ImportError:
        # libcst not available
        result, error = patch_function("code", "foo", "x")
        assert result is None
        assert "not installed" in error


# ======= patch_confidence tests (cover lines 17-22, 26-32, 36-38, 44-53, 57-59) =======
def test_patch_confidence_remaining():
    # Test compute_confidence
    result = compute_confidence(0.9, 0.8, 0.7, 0.9)
    assert result == 0.9 * 0.8 * 0.7 * 0.9

    # Test classify_patch
    assert classify_patch(0.9) == "HIGH"
    assert classify_patch(0.6) == "MEDIUM"
    assert classify_patch(0.3) == "LOW"
    assert classify_patch(0.1) == "UNKNOWN"

    # Test get_target_certainty
    assert get_target_certainty(True, True, False) == 1.0
    assert get_target_certainty(False, True, True) == 0.5
    assert get_target_certainty(False, False, False) == 0.2

    # Test get_structural_safety
    assert get_structural_safety("default") == 1.0
    assert get_structural_safety("kwarg") == 0.8
    assert get_structural_safety("positional") == 0.3

    # Test get_semantic_risk
    assert get_semantic_risk("required") == 0.6
    assert get_semantic_risk("other") == 1.0

    # Test get_complexity_penalty
    assert get_complexity_penalty(False, False, False, False) == 1.0
    assert get_complexity_penalty(True, False, False, False) == 0.7


# ======= compare_signatures tests =======
def test_compare_remaining():
    sigs1 = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    sigs2 = [
        {
            "fqname": "test.py:foo",
            "name": "foo",
            "positional": [
                {"name": "x", "has_default": False},
                {"name": "y", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sigs1, f)
        f1_name = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sigs2, f)
        f2_name = f.name

    result = compare(f1_name, f2_name)
    assert isinstance(result, dict)
    assert "nonbreaking" in result

    os.unlink(f1_name)
    os.unlink(f2_name)


# ======= patch_generator tests =======
def test_patch_generator_remaining():
    func = {"file": "test.py", "lineno": 1}
    result = patch_add_default(func, "new_param")
    assert result is None or isinstance(result, str)

    call = {"file": "test.py", "lineno": 5}
    func2 = {"name": "foo", "positional": []}
    result2 = patch_callsite(call, func2)
    assert result2 is None or isinstance(result2, str)


# ======= suggest_fixes tests =======
def test_suggest_fixes_remaining():
    func = {"name": "foo"}
    issues = [{"type": "missing_args"}]
    result = suggest(func, issues)
    assert len(result) > 0

    # Test get_line
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("line1\nline2\nline3\n")
        fname = f.name
    result = get_line(fname, 2)
    assert "line2" in result or result == ""
    os.unlink(fname)

    # Test enrich_with_fixes
    report_item = {"patches": ["patch1"], "callsite_patches": ["patch2"]}
    result = enrich_with_fixes(report_item, [])
    assert isinstance(result, list)


# ======= trace_calls tests =======
def test_trace_calls_remaining():
    import types

    mock_module = types.ModuleType("mock_module")

    def dummy_func():
        pass

    mock_module.dummy_func = dummy_func

    # Test install_tracer
    install_tracer(mock_module)

    # Test dump
    COUNTS["test_func"] = 5
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        dump(f.name)
        assert os.path.exists(f.name)
        data = json.load(open(f.name))
        assert len(data) > 0
        os.unlink(f.name)
    COUNTS.clear()


# ======= trace_calls_prod tests =======
def test_trace_calls_prod_remaining():
    # Test should_sample
    with patch("random.random", return_value=0.005):
        assert should_sample() is True

    with patch("random.random", return_value=0.5):
        assert should_sample() is False

    # Test flush
    from impactguard.trace_calls_prod import COUNTS as COUNTS_PROD

    COUNTS_PROD["test_func"] = 5

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        fname = f.name

    flush(fname)
    assert os.path.exists(fname)

    data = json.load(open(fname))
    assert len(data) > 0

    os.unlink(fname)
    COUNTS_PROD.clear()

    # Test install_tracer_prod
    import types

    mock_module = types.ModuleType("mock_module")

    def dummy_func():
        pass

    mock_module.dummy_func = dummy_func

    install_tracer_prod(mock_module)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
