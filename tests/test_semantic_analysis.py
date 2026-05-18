"""Tests for semantic behavior analysis (semantic_analysis.py)."""

import json
import textwrap
import tempfile
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from impactguard.semantic_analysis import (
    SEMANTIC_SEVERITY,
    analyze_behavior,
    compare_behavior,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_py(content: str) -> str:
    """Write *content* to a temporary .py file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as f:
        f.write(textwrap.dedent(content))
        return f.name


# ── SEMANTIC_SEVERITY ─────────────────────────────────────────────────────────


def test_semantic_severity_keys():
    expected = {
        "ASYNC_CHANGED",
        "YIELD_REMOVED",
        "YIELD_ADDED",
        "SIDE_EFFECT_ADDED",
        "EXCEPTION_ADDED",
        "RETURNS_NONE_CHANGED",
        "SIDE_EFFECT_REMOVED",
        "CONTRACT_CHANGED",
        "CONTRACT_REMOVED",
        "EXCEPTION_REMOVED",
    }
    assert expected <= set(SEMANTIC_SEVERITY.keys())


def test_semantic_severity_values_in_range():
    for key, val in SEMANTIC_SEVERITY.items():
        assert 0.0 <= val <= 1.0, f"{key}={val} out of [0, 1]"


def test_semantic_severity_ordering():
    # Breaking changes should have higher severity than informational ones
    assert SEMANTIC_SEVERITY["ASYNC_CHANGED"] >= SEMANTIC_SEVERITY["EXCEPTION_ADDED"]
    assert SEMANTIC_SEVERITY["EXCEPTION_ADDED"] > SEMANTIC_SEVERITY["EXCEPTION_REMOVED"]
    assert SEMANTIC_SEVERITY["SIDE_EFFECT_ADDED"] > SEMANTIC_SEVERITY["SIDE_EFFECT_REMOVED"]


# ── analyze_behavior ──────────────────────────────────────────────────────────


def test_analyze_behavior_basic_function():
    path = _write_py("""
        def simple(x):
            return x + 1
    """)
    try:
        traits = analyze_behavior([path])
        assert len(traits) == 1
        fqname = next(iter(traits))
        t = traits[fqname]
        assert t["raises"] == []
        assert t["has_yield"] is False
        assert t["is_async"] is False
        assert t["always_returns_none"] is False
    finally:
        os.unlink(path)


def test_analyze_behavior_is_async():
    path = _write_py("""
        async def fetch(url):
            return url
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert t["is_async"] is True
        assert t["always_returns_none"] is False
    finally:
        os.unlink(path)


def test_analyze_behavior_generator():
    path = _write_py("""
        def gen():
            yield 1
            yield 2
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert t["has_yield"] is True
    finally:
        os.unlink(path)


def test_analyze_behavior_always_returns_none():
    path = _write_py("""
        def void_func():
            print("hello")
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert t["always_returns_none"] is True
    finally:
        os.unlink(path)


def test_analyze_behavior_explicit_return_none():
    path = _write_py("""
        def explicit_none():
            return None
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert t["always_returns_none"] is True
    finally:
        os.unlink(path)


def test_analyze_behavior_raises():
    path = _write_py("""
        def strict(x):
            if x < 0:
                raise ValueError("negative")
            if x == 0:
                raise ZeroDivisionError
            return 1 / x
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert "ValueError" in t["raises"]
        assert "ZeroDivisionError" in t["raises"]
    finally:
        os.unlink(path)


def test_analyze_behavior_side_effect_file_io():
    path = _write_py("""
        def write_file(path, data):
            with open(path, "w") as f:
                f.write(data)
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert "file_io" in t["side_effects"]
    finally:
        os.unlink(path)


def test_analyze_behavior_side_effect_stdout():
    path = _write_py("""
        def greet(name):
            print(f"Hello, {name}")
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert "stdout_write" in t["side_effects"]
    finally:
        os.unlink(path)


def test_analyze_behavior_side_effect_global():
    path = _write_py("""
        COUNTER = 0

        def increment():
            global COUNTER
            COUNTER += 1
    """)
    try:
        traits = analyze_behavior([path])
        # Find increment function
        fqname = next(k for k in traits if "increment" in k)
        t = traits[fqname]
        assert "global_mutation" in t["side_effects"]
    finally:
        os.unlink(path)


def test_analyze_behavior_side_effect_self_mutation():
    path = _write_py("""
        class Foo:
            def update(self, value):
                self.value = value
    """)
    try:
        traits = analyze_behavior([path])
        fqname = next(k for k in traits if "update" in k)
        t = traits[fqname]
        assert "self_mutation" in t["side_effects"]
    finally:
        os.unlink(path)


def test_analyze_behavior_side_effect_os_call():
    path = _write_py("""
        import os

        def delete_file(path):
            os.remove(path)
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert "os_call" in t["side_effects"]
    finally:
        os.unlink(path)


def test_analyze_behavior_docstring_hash():
    path = _write_py("""
        def documented():
            \"\"\"This function does something important.\"\"\"
            return 42
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert t["docstring_hash"] is not None
        assert len(t["docstring_hash"]) == 8
    finally:
        os.unlink(path)


def test_analyze_behavior_no_docstring():
    path = _write_py("""
        def undocumented():
            return 42
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert t["docstring_hash"] is None
    finally:
        os.unlink(path)


def test_analyze_behavior_method_fqname():
    path = _write_py("""
        class MyClass:
            def my_method(self):
                pass
    """)
    try:
        traits = analyze_behavior([path])
        fqnames = list(traits.keys())
        assert any("MyClass.my_method" in k for k in fqnames)
    finally:
        os.unlink(path)


def test_analyze_behavior_multiple_functions():
    path = _write_py("""
        def func_a():
            return 1

        def func_b():
            raise RuntimeError("oops")
    """)
    try:
        traits = analyze_behavior([path])
        assert len(traits) == 2
        fq_b = next(k for k in traits if "func_b" in k)
        assert "RuntimeError" in traits[fq_b]["raises"]
    finally:
        os.unlink(path)


def test_analyze_behavior_base_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        pyfile = Path(tmpdir) / "module.py"
        pyfile.write_text(textwrap.dedent("""
            def hello():
                return "hi"
        """))
        traits = analyze_behavior([str(pyfile)], base_path=tmpdir)
        fqname = next(iter(traits))
        # Should use relative path: "module.py:hello"
        assert "module.py" in fqname


def test_analyze_behavior_parse_error_skipped():
    path = _write_py("def broken(: syntax error")
    try:
        # Should not raise; just skip the bad file
        traits = analyze_behavior([path])
        assert traits == {}
    finally:
        os.unlink(path)


def test_analyze_behavior_yield_from():
    path = _write_py("""
        def delegating():
            yield from range(10)
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert t["has_yield"] is True
    finally:
        os.unlink(path)


def test_analyze_behavior_nested_function_not_in_parent():
    """Nested function's exceptions should not appear in parent's traits."""
    path = _write_py("""
        def outer():
            def inner():
                raise ValueError("from inner")
            return inner
    """)
    try:
        traits = analyze_behavior([path])
        fq_outer = next(k for k in traits if "outer" in k and "inner" not in k)
        assert "ValueError" not in traits[fq_outer]["raises"]
    finally:
        os.unlink(path)


def test_analyze_behavior_network_call():
    path = _write_py("""
        import requests

        def fetch(url):
            return requests.get(url)
    """)
    try:
        traits = analyze_behavior([path])
        t = next(iter(traits.values()))
        assert "network_call" in t["side_effects"]
    finally:
        os.unlink(path)


# ── compare_behavior ──────────────────────────────────────────────────────────


def _make_traits(**kwargs) -> dict:
    base = {
        "raises": [],
        "side_effects": [],
        "has_yield": False,
        "is_async": False,
        "always_returns_none": True,
        "docstring_hash": None,
    }
    base.update(kwargs)
    return base


def test_compare_behavior_no_changes():
    traits = {"mod.py:foo": _make_traits()}
    result = compare_behavior(traits, traits)
    assert result["semantic_breaking"] == []
    assert result["semantic_nonbreaking"] == []


def test_compare_behavior_async_changed_sync_to_async():
    old = {"mod.py:foo": _make_traits(is_async=False)}
    new = {"mod.py:foo": _make_traits(is_async=True)}
    result = compare_behavior(old, new)
    assert any("ASYNC_CHANGED" in s for s in result["semantic_breaking"])
    assert any("sync→async" in s for s in result["semantic_breaking"])


def test_compare_behavior_async_changed_async_to_sync():
    old = {"mod.py:foo": _make_traits(is_async=True)}
    new = {"mod.py:foo": _make_traits(is_async=False)}
    result = compare_behavior(old, new)
    assert any("ASYNC_CHANGED" in s for s in result["semantic_breaking"])
    assert any("async→sync" in s for s in result["semantic_breaking"])


def test_compare_behavior_yield_added():
    old = {"mod.py:foo": _make_traits(has_yield=False)}
    new = {"mod.py:foo": _make_traits(has_yield=True)}
    result = compare_behavior(old, new)
    assert any("YIELD_ADDED" in s for s in result["semantic_breaking"])


def test_compare_behavior_yield_removed():
    old = {"mod.py:foo": _make_traits(has_yield=True)}
    new = {"mod.py:foo": _make_traits(has_yield=False)}
    result = compare_behavior(old, new)
    assert any("YIELD_REMOVED" in s for s in result["semantic_breaking"])


def test_compare_behavior_exception_added():
    old = {"mod.py:foo": _make_traits(raises=[])}
    new = {"mod.py:foo": _make_traits(raises=["ValueError"])}
    result = compare_behavior(old, new)
    assert any("EXCEPTION_ADDED" in s and "ValueError" in s for s in result["semantic_breaking"])


def test_compare_behavior_exception_removed():
    old = {"mod.py:foo": _make_traits(raises=["ValueError"])}
    new = {"mod.py:foo": _make_traits(raises=[])}
    result = compare_behavior(old, new)
    assert any("EXCEPTION_REMOVED" in s and "ValueError" in s for s in result["semantic_nonbreaking"])


def test_compare_behavior_side_effect_added():
    old = {"mod.py:foo": _make_traits(side_effects=[])}
    new = {"mod.py:foo": _make_traits(side_effects=["file_io"])}
    result = compare_behavior(old, new)
    assert any("SIDE_EFFECT_ADDED" in s and "file_io" in s for s in result["semantic_breaking"])


def test_compare_behavior_side_effect_removed():
    old = {"mod.py:foo": _make_traits(side_effects=["stdout_write"])}
    new = {"mod.py:foo": _make_traits(side_effects=[])}
    result = compare_behavior(old, new)
    assert any("SIDE_EFFECT_REMOVED" in s and "stdout_write" in s for s in result["semantic_nonbreaking"])


def test_compare_behavior_returns_none_changed():
    old = {"mod.py:foo": _make_traits(always_returns_none=False)}
    new = {"mod.py:foo": _make_traits(always_returns_none=True)}
    result = compare_behavior(old, new)
    assert any("RETURNS_NONE_CHANGED" in s for s in result["semantic_breaking"])


def test_compare_behavior_contract_changed():
    old = {"mod.py:foo": _make_traits(docstring_hash="aabbccdd")}
    new = {"mod.py:foo": _make_traits(docstring_hash="11223344")}
    result = compare_behavior(old, new)
    assert any("CONTRACT_CHANGED" in s for s in result["semantic_nonbreaking"])


def test_compare_behavior_contract_removed():
    old = {"mod.py:foo": _make_traits(docstring_hash="aabbccdd")}
    new = {"mod.py:foo": _make_traits(docstring_hash=None)}
    result = compare_behavior(old, new)
    assert any("CONTRACT_REMOVED" in s for s in result["semantic_nonbreaking"])


def test_compare_behavior_no_docstring_change_if_both_none():
    old = {"mod.py:foo": _make_traits(docstring_hash=None)}
    new = {"mod.py:foo": _make_traits(docstring_hash=None)}
    result = compare_behavior(old, new)
    assert not any("CONTRACT" in s for s in result["semantic_nonbreaking"])


def test_compare_behavior_function_absent_in_old():
    """New-only functions (ADDED) are not analyzed — no semantic changes expected."""
    old: dict = {}
    new = {"mod.py:foo": _make_traits(is_async=True)}
    result = compare_behavior(old, new)
    assert result["semantic_breaking"] == []
    assert result["semantic_nonbreaking"] == []


def test_compare_behavior_function_removed():
    """Removed functions are handled by compare_signatures, not here."""
    old = {"mod.py:foo": _make_traits(is_async=True)}
    new: dict = {}
    result = compare_behavior(old, new)
    assert result["semantic_breaking"] == []
    assert result["semantic_nonbreaking"] == []


def test_compare_behavior_multiple_changes():
    old = {
        "mod.py:foo": _make_traits(
            is_async=False,
            raises=["ValueError"],
            side_effects=["stdout_write"],
        )
    }
    new = {
        "mod.py:foo": _make_traits(
            is_async=True,
            raises=["TypeError"],
            side_effects=["file_io"],
        )
    }
    result = compare_behavior(old, new)
    breaking = result["semantic_breaking"]
    nonbreaking = result["semantic_nonbreaking"]

    assert any("ASYNC_CHANGED" in s for s in breaking)
    assert any("EXCEPTION_ADDED" in s and "TypeError" in s for s in breaking)
    assert any("SIDE_EFFECT_ADDED" in s and "file_io" in s for s in breaking)
    assert any("EXCEPTION_REMOVED" in s and "ValueError" in s for s in nonbreaking)
    assert any("SIDE_EFFECT_REMOVED" in s and "stdout_write" in s for s in nonbreaking)


def test_compare_behavior_deduplication():
    """Duplicate change strings should be collapsed."""
    old = {
        "mod.py:foo": _make_traits(raises=["ValueError"]),
        "mod.py:bar": _make_traits(raises=["ValueError"]),
    }
    new = {
        "mod.py:foo": _make_traits(raises=["TypeError"]),
        "mod.py:bar": _make_traits(raises=["TypeError"]),
    }
    result = compare_behavior(old, new)
    # Both functions trigger EXCEPTION_ADDED, but they're different fqnames
    assert len([s for s in result["semantic_breaking"] if "EXCEPTION_ADDED" in s]) == 2


# ── Integration: analyze_behavior + compare_behavior ─────────────────────────


def test_end_to_end_async_change():
    old_path = _write_py("""
        def fetch(url):
            return url
    """)
    new_path = _write_py("""
        async def fetch(url):
            return url
    """)
    try:
        old_traits = analyze_behavior([old_path])
        new_traits = analyze_behavior([new_path])
        # Remap to same fqname for comparison
        old_fq = next(iter(old_traits))
        new_fq = next(iter(new_traits))
        merged_old = {old_fq: old_traits[old_fq]}
        merged_new = {old_fq: new_traits[new_fq]}

        result = compare_behavior(merged_old, merged_new)
        assert any("ASYNC_CHANGED" in s for s in result["semantic_breaking"])
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


def test_end_to_end_exception_contract():
    old_path = _write_py("""
        def divide(a, b):
            return a / b
    """)
    new_path = _write_py("""
        def divide(a, b):
            if b == 0:
                raise ZeroDivisionError("cannot divide by zero")
            return a / b
    """)
    try:
        old_traits = analyze_behavior([old_path])
        new_traits = analyze_behavior([new_path])
        old_fq = next(iter(old_traits))
        new_fq = next(iter(new_traits))
        merged_old = {old_fq: old_traits[old_fq]}
        merged_new = {old_fq: new_traits[new_fq]}

        result = compare_behavior(merged_old, merged_new)
        assert any("EXCEPTION_ADDED" in s and "ZeroDivisionError" in s
                   for s in result["semantic_breaking"])
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


def test_end_to_end_side_effect_added():
    old_path = _write_py("""
        def process(data):
            return data.strip()
    """)
    new_path = _write_py("""
        def process(data):
            with open("/tmp/log.txt", "a") as f:
                f.write(data)
            return data.strip()
    """)
    try:
        old_traits = analyze_behavior([old_path])
        new_traits = analyze_behavior([new_path])
        old_fq = next(iter(old_traits))
        new_fq = next(iter(new_traits))
        merged_old = {old_fq: old_traits[old_fq]}
        merged_new = {old_fq: new_traits[new_fq]}

        result = compare_behavior(merged_old, merged_new)
        assert any("SIDE_EFFECT_ADDED" in s and "file_io" in s
                   for s in result["semantic_breaking"])
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


# ── CLI integration ───────────────────────────────────────────────────────────


def test_cli_analyze_behavior(tmp_path):
    """Test the analyze-behavior CLI subcommand outputs change counts."""
    old_file = tmp_path / "old.py"
    new_file = tmp_path / "new.py"

    old_file.write_text(textwrap.dedent("""
        def compute(x):
            return x * 2
    """))
    new_file.write_text(textwrap.dedent("""
        async def compute(x):
            return x * 2
    """))

    import argparse
    from impactguard.__main__ import cmd_analyze_behavior
    import io
    import contextlib

    args = argparse.Namespace(
        old=str(old_file),
        new=str(new_file),
        base_path=None,
        output=None,
    )

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        cmd_analyze_behavior(args)

    output = captured.getvalue()
    assert "Semantic breaking changes:" in output
    assert "Semantic non-breaking changes:" in output


def test_cli_analyze_behavior_json_output(tmp_path):
    """analyze-behavior writes valid JSON with expected keys to --output file."""
    old_file = tmp_path / "old.py"
    new_file = tmp_path / "new.py"
    out_file = tmp_path / "diff.json"

    old_file.write_text("def func(): return 1\n")
    new_file.write_text("async def func(): return 1\n")

    import argparse
    from impactguard.__main__ import cmd_analyze_behavior

    args = argparse.Namespace(
        old=str(old_file),
        new=str(new_file),
        base_path=None,
        output=str(out_file),
    )
    cmd_analyze_behavior(args)

    assert out_file.exists(), "Output JSON file should be created"
    data = json.loads(out_file.read_text())
    assert "semantic_breaking" in data
    assert "semantic_nonbreaking" in data


# ── risk_model integration ────────────────────────────────────────────────────


def test_risk_model_knows_semantic_types():
    """Semantic change types should be recognized by risk_model.get_severity."""
    from impactguard.risk_model import get_severity, SEVERITY_SCORES

    for change_type in SEMANTIC_SEVERITY:
        sev = get_severity(change_type + ": mod.py:func")
        assert sev > 0.0, f"Severity for {change_type} should be positive"
        # Ensure it's in SEVERITY_SCORES, not falling through to default 0.5
        assert change_type in SEVERITY_SCORES, (
            f"{change_type} missing from SEVERITY_SCORES"
        )


def test_risk_model_async_changed_severity():
    from impactguard.risk_model import get_severity

    sev = get_severity("ASYNC_CHANGED: mod.py:foo (sync→async)")
    assert sev == 0.8


def test_risk_model_exception_added_severity():
    from impactguard.risk_model import get_severity

    sev = get_severity("EXCEPTION_ADDED: mod.py:foo raises ValueError")
    assert sev == 0.5
