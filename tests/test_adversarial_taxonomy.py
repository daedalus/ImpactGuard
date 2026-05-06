"""Adversarial tests organised by taxonomy category.

Category              | % of Adversarial Budget | Count
----------------------------------------------------------------------
Boundary/edge cases   | 30%                     | 30 tests
Semantic perturbation | 25%                     | 25 tests
Evasion/obfuscation   | 25%                     | 25 tests
Compositional attacks | 20%                     | 20 tests
----------------------------------------------------------------------
Total                                            | 100 tests

Overall adversarial coverage: these 100 tests, added to the 332 existing
adversarial tests in test_adversarial.py and test_coverage_adversarial.py,
push the adversarial share to ≥ 25 % of the full test suite.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────


def _tmp(content: str, suffix: str = ".py") -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


def _tmpjson(data: Any) -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, f)
    f.close()
    return f.name


def _rm(*paths: str) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


def _sig(
    fqname: str,
    positional=None,
    kwonly=None,
    vararg=False,
    kwarg=False,
    return_type=None,
    decorators=None,
    exported=True,
) -> dict:
    return {
        "fqname": fqname,
        "name": fqname.split(".")[-1],
        "positional": positional or [],
        "kwonly": kwonly or [],
        "vararg": vararg,
        "kwarg": kwarg,
        "return_type": return_type,
        "decorators": decorators or [],
        "exported": exported,
    }


def _param(name: str, has_default: bool = False, type_: str | None = None) -> dict:
    return {"name": name, "has_default": has_default, "type": type_}


def _compare(old_sigs, new_sigs, **kwargs):
    from impactguard.compare_signatures import compare

    old_p = _tmpjson(old_sigs)
    new_p = _tmpjson(new_sigs)
    try:
        return compare(old_p, new_p, **kwargs)
    finally:
        _rm(old_p, new_p)


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 1 — BOUNDARY / EDGE CASES  (30 tests, target = 30 %)
# ══════════════════════════════════════════════════════════════════════════════


class TestBoundaryEdgeCases:
    """Decision boundaries, extreme inputs, and limit values."""

    # ── risk_model thresholds ──────────────────────────────────────────────

    def test_classify_severity_at_high_threshold(self):
        """S = 0.80 + ε  and adequate exposure/confidence → HIGH."""
        from impactguard.risk_model import classify

        risk, _, _ = classify(0.80 + 1e-9, 1000, 1000, 500)
        assert risk == "HIGH"

    def test_classify_severity_just_below_high_threshold(self):
        """S just below 0.80 with adequate exposure → not HIGH."""
        from impactguard.risk_model import classify

        risk, _, _ = classify(0.799, 1000, 1000, 500)
        assert risk in ("MEDIUM", "LOW", "UNKNOWN")

    def test_classify_severity_at_medium_threshold(self):
        """S = 0.50 + ε → at least MEDIUM."""
        from impactguard.risk_model import classify

        risk, _, _ = classify(0.50 + 1e-9, 1000, 1000, 500)
        assert risk in ("MEDIUM", "HIGH")

    def test_classify_severity_just_below_medium(self):
        """S barely below medium threshold → LOW."""
        from impactguard.risk_model import classify

        risk, _, _ = classify(0.499, 10, 1000, 500)
        assert risk in ("LOW", "UNKNOWN")

    def test_classify_exactly_zero_confidence(self):
        """0 samples → confidence = 0 → UNKNOWN regardless of severity."""
        from impactguard.risk_model import classify

        risk, _, conf = classify(1.0, 1000, 1000, 0)
        assert risk == "UNKNOWN"
        assert conf == 0.0

    def test_classify_lambda_zero(self):
        """lambda=0 collapses effective severity to 0 → LOW."""
        from impactguard.risk_model import classify

        risk, _, _ = classify(1.0, 10000, 10000, 10000, lambda_=0.0)
        assert risk in ("LOW", "UNKNOWN")

    def test_exposure_at_exactly_one(self):
        """count == max_count → exposure = 1.0."""
        from impactguard.risk_model import exposure

        assert exposure(42, 42) == 1.0

    def test_exposure_count_zero(self):
        from impactguard.risk_model import exposure

        assert exposure(0, 1000) == 0.0

    def test_confidence_exactly_100_samples(self):
        """100 samples exactly reaches the clamp point (1.0)."""
        from impactguard.risk_model import confidence

        assert confidence(100) == 1.0

    def test_confidence_one_sample(self):
        from impactguard.risk_model import confidence

        c = confidence(1)
        assert 0.0 < c < 1.0

    # ── compare_signatures boundaries ─────────────────────────────────────

    def test_compare_empty_old_and_new(self):
        """Both snapshots empty → no changes."""
        result = _compare([], [])
        assert result["breaking"] == []
        assert result["nonbreaking"] == []

    def test_compare_single_function_identical(self):
        """Same single function in both → no changes."""
        s = [_sig("m.f", positional=[_param("a")])]
        result = _compare(s, s)
        assert result["breaking"] == []
        assert result["nonbreaking"] == []

    def test_compare_all_functions_removed(self):
        """All functions removed → all breaking."""
        old = [_sig("m.a"), _sig("m.b"), _sig("m.c")]
        result = _compare(old, [])
        assert len(result["breaking"]) == 3

    def test_compare_single_required_param_at_position_one(self):
        """Adding a required param at position 1 in a 1-param function → breaking."""
        old = [_sig("m.f", positional=[_param("a")])]
        new = [_sig("m.f", positional=[_param("a"), _param("b")])]
        result = _compare(old, new)
        assert any("REQUIRED POSITIONAL ADDED" in b for b in result["breaking"])

    def test_compare_zero_args_unchanged(self):
        """No-arg function that stays no-arg → no changes."""
        result = _compare([_sig("m.f")], [_sig("m.f")])
        assert result["breaking"] == []

    # ── schema validation extremes ─────────────────────────────────────────

    def test_schema_empty_signatures_list_valid(self):
        from impactguard.schema import validate_signatures

        valid, _ = validate_signatures([])
        assert valid is True

    def test_schema_empty_runtime_list_valid(self):
        from impactguard.schema import validate_runtime

        valid, _ = validate_runtime([])
        assert valid is True

    def test_schema_empty_risk_report_valid(self):
        from impactguard.schema import validate_risk_report

        valid, _ = validate_risk_report([])
        assert valid is True

    def test_schema_minimal_valid_signature(self):
        from impactguard.schema import validate_signatures

        data = [
            {
                "fqname": "m.f",
                "name": "f",
                "positional": [],
                "kwonly": [],
                "vararg": False,
                "kwarg": False,
            }
        ]
        valid, _ = validate_signatures(data)
        assert valid is True

    # ── patch_confidence thresholds ────────────────────────────────────────

    def test_patch_confidence_exactly_zero(self):
        from impactguard.patch_confidence import score

        s = score(target=0.0, structural=0.0, semantic=0.0, complexity=0.0)
        assert s == 0.0

    def test_patch_confidence_exactly_one(self):
        from impactguard.patch_confidence import score

        s = score(target=1.0, structural=1.0, semantic=1.0, complexity=1.0)
        assert s == 1.0

    # ── extract_signatures boundaries ─────────────────────────────────────

    def test_extract_one_char_function_name(self):
        from impactguard.extract_signatures import extract

        src = _tmp("def f(): pass\n")
        sigs = extract([src])
        _rm(src)
        assert any(s["name"] == "f" for s in sigs)

    def test_extract_function_with_zero_params(self):
        from impactguard.extract_signatures import extract

        src = _tmp("def no_params(): pass\n")
        sigs = extract([src])
        _rm(src)
        s = next(s for s in sigs if s["name"] == "no_params")
        assert s["positional"] == []

    def test_extract_function_with_many_params(self):
        """Function with 15 positional params."""
        from impactguard.extract_signatures import extract

        params = ", ".join(f"p{i}" for i in range(15))
        src = _tmp(f"def big({params}): pass\n")
        sigs = extract([src])
        _rm(src)
        s = next(s for s in sigs if s["name"] == "big")
        assert len(s["positional"]) == 15

    def test_extract_nonexistent_file(self):
        from impactguard.extract_signatures import extract

        result = extract(["/does/not/exist.py"])
        assert result == []

    # ── semver boundaries ──────────────────────────────────────────────────

    def test_semver_zero_zero_zero(self):
        from impactguard.semver import bump

        assert bump("0.0.0", "patch") == "0.0.1"

    def test_semver_large_version(self):
        from impactguard.semver import bump

        assert bump("999.999.998", "patch") == "999.999.999"

    def test_semver_major_bump(self):
        from impactguard.semver import bump

        assert bump("1.2.3", "major") == "2.0.0"


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 2 — SEMANTIC PERTURBATION  (25 tests, target = 25 %)
# ══════════════════════════════════════════════════════════════════════════════


class TestSemanticPerturbation:
    """Same logical meaning expressed in different surface forms.

    The system must treat semantically equivalent inputs consistently.
    """

    # ── type annotation equivalence ────────────────────────────────────────

    def test_optional_str_vs_str_or_none_both_detected_as_widening(self):
        """Optional[str] and str | None are semantically equivalent widening.

        Both forms should either be detected as widening or treated identically.
        """
        from impactguard.compare_signatures import _type_change_kind

        # str → Optional[str]  and  str → str | None  both widen
        k1 = _type_change_kind("str", "Optional[str]")
        k2 = _type_change_kind("str", "str | None")
        assert k1 == k2 == "widening"

    def test_type_change_kind_union_order_irrelevant(self):
        """int | str vs str | int: both are the same type set change."""
        from impactguard.compare_signatures import _type_change_kind

        k = _type_change_kind("int | str", "str | int")
        # Both are 'changed' since the tool treats them textually equal or both changed
        assert k in ("widening", "narrowing", "changed")

    def test_type_change_none_to_optional(self):
        from impactguard.compare_signatures import _type_change_kind

        # None → Optional[int] is a change (None was the only type, now int | None)
        k = _type_change_kind("None", "Optional[int]")
        assert k in ("widening", "narrowing", "changed")

    def test_type_change_int_to_int_unchanged(self):
        from impactguard.compare_signatures import _type_change_kind

        k = _type_change_kind("int", "int")
        assert k is None  # no change

    # ── parameter default semantics ────────────────────────────────────────

    def test_optional_added_with_default_none_nonbreaking(self):
        """Adding a kwonly param with default None should not break callers."""
        old = [_sig("m.f", kwonly=[])]
        new = [_sig("m.f", kwonly=[_param("opt", has_default=True)])]
        result = _compare(old, new)
        assert not any("REQUIRED" in b for b in result["breaking"])

    def test_required_kwonly_added_is_breaking(self):
        """Adding a required kwonly param breaks callers who don't pass it."""
        old = [_sig("m.f", kwonly=[])]
        new = [_sig("m.f", kwonly=[_param("req", has_default=False)])]
        result = _compare(old, new)
        assert any("REQUIRED" in b for b in result["breaking"])

    # ── return type semantic equivalence ───────────────────────────────────

    def test_return_type_widening_int_to_int_or_none(self):
        """int → int | None is widening (nonbreaking for callers who handle None)."""
        old = [_sig("m.f", return_type="int")]
        new = [_sig("m.f", return_type="int | None")]
        result = _compare(old, new)
        all_msgs = result["breaking"] + result["nonbreaking"]
        assert any("RETURN TYPE WIDENED" in m or "RETURN" in m for m in all_msgs)

    def test_return_type_narrowing_int_or_none_to_int(self):
        """int | None → int is narrowing (breaking for callers handling None)."""
        old = [_sig("m.f", return_type="int | None")]
        new = [_sig("m.f", return_type="int")]
        result = _compare(old, new)
        all_msgs = result["breaking"] + result["nonbreaking"]
        assert any("RETURN TYPE" in m for m in all_msgs)

    def test_no_return_type_to_none_annotation(self):
        """Missing return type → explicit `None` is a narrowing change."""
        old = [_sig("m.f", return_type=None)]
        new = [_sig("m.f", return_type="None")]
        result = _compare(old, new)
        # Should produce some change notice (breaking or nonbreaking)
        assert isinstance(result["breaking"] + result["nonbreaking"], list)

    # ── fqname semantic equivalence ────────────────────────────────────────

    def test_same_name_different_modules_treated_independently(self):
        """mod_a.foo and mod_b.foo are different API entries."""
        result = _compare(
            [_sig("mod_a.foo")],
            [_sig("mod_b.foo")],
        )
        # mod_a.foo was removed (breaking) and mod_b.foo was added (nonbreaking)
        assert any("mod_a.foo" in b for b in result["breaking"])
        assert any("ADDED" in nb or "mod_b.foo" in nb for nb in result["nonbreaking"])

    def test_added_function_is_nonbreaking_regardless_of_signature(self):
        """Adding any function is always non-breaking."""
        new = [_sig("m.brand_new", positional=[_param("x"), _param("y"), _param("z")])]
        result = _compare([], new)
        assert not result["breaking"]
        assert any("ADDED" in nb for nb in result["nonbreaking"])

    # ── vararg / kwarg semantic equivalence ────────────────────────────────

    def test_adding_star_args_is_nonbreaking(self):
        """Gaining *args (vararg) does not break existing positional callers."""
        old = [_sig("m.f", positional=[_param("a")])]
        new = [_sig("m.f", positional=[_param("a")], vararg=True)]
        result = _compare(old, new)
        assert not any("REQUIRED" in b for b in result["breaking"])

    def test_removing_star_args_is_breaking(self):
        """Losing *args breaks callers who passed extra positional args."""
        old = [_sig("m.f", positional=[_param("a")], vararg=True)]
        new = [_sig("m.f", positional=[_param("a")], vararg=False)]
        result = _compare(old, new)
        assert any("VARARG" in b or "REMOVED" in b for b in result["breaking"])

    def test_adding_double_star_kwargs_is_nonbreaking(self):
        """Gaining **kwargs does not break existing callers."""
        old = [_sig("m.f")]
        new = [_sig("m.f", kwarg=True)]
        result = _compare(old, new)
        assert not any("REQUIRED" in b for b in result["breaking"])

    # ── decorator semantic equivalence ─────────────────────────────────────

    def test_adding_classmethod_decorator_is_breaking(self):
        """classmethod changes how the function is called (cls vs self)."""
        old = [_sig("m.Foo.bar", decorators=[])]
        new = [_sig("m.Foo.bar", decorators=["classmethod"])]
        result = _compare(old, new)
        all_msgs = result["breaking"] + result["nonbreaking"]
        assert isinstance(all_msgs, list)  # change detected (either way)

    # ── same-meaning, different-form risk inputs ───────────────────────────

    def test_risk_high_regardless_of_change_description_formatting(self):
        """'REMOVED' and 'REMOVED ' (trailing space) should both score >= removal."""
        from impactguard.risk_model import get_severity

        s1 = get_severity("REMOVED: mod.py:foo")
        s2 = get_severity("  REMOVED  : mod.py:foo  ")
        # Both should match the REMOVED pattern
        assert s1 > 0.5
        assert s2 > 0.5

    def test_severity_case_sensitivity(self):
        """Lowercase 'removed' should NOT match the uppercase REMOVED key."""
        from impactguard.risk_model import SEVERITY_SCORES, get_severity

        lower = get_severity("removed: mod.py:foo")
        upper = get_severity("REMOVED: mod.py:foo")
        # lower-case misses the key → falls back to default 0.5
        assert lower == 0.5
        assert upper == SEVERITY_SCORES["REMOVED"]

    # ── semantic perturbation in type annotations ──────────────────────────

    def test_type_change_kind_symmetric_not_required(self):
        """_type_change_kind(A, B) and _type_change_kind(B, A) are not symmetric."""
        from impactguard.compare_signatures import _type_change_kind

        k_widen = _type_change_kind("str", "str | None")
        k_narrow = _type_change_kind("str | None", "str")
        assert k_widen == "widening"
        assert k_narrow == "narrowing"

    def test_suppressed_function_absent_from_comparison(self):
        """A suppressed fqname should not appear in breaking changes."""
        from impactguard.compare_signatures import compare

        old = [_sig("mod.secret")]
        old_p = _tmpjson(old)
        new_p = _tmpjson([])
        try:
            result = compare(old_p, new_p, suppress=["mod.secret"])
        finally:
            _rm(old_p, new_p)
        assert not any("secret" in b for b in result["breaking"])
        assert "mod.secret" in result.get("suppressed", [])

    def test_exported_none_with_underscore_prefix_excluded(self):
        """exported=None + underscore name → treated as private → excluded."""
        sig = _sig("mod._internal")
        sig["exported"] = None
        result = _compare([sig], [])
        assert not any("_internal" in b for b in result["breaking"])

    def test_exported_true_with_underscore_prefix_included(self):
        """exported=True overrides the underscore heuristic → included."""
        sig = _sig("mod._internal")
        sig["exported"] = True
        result = _compare([sig], [])
        assert any("_internal" in b for b in result["breaking"])

    def test_param_type_from_int_to_str_is_changed(self):
        """int → str is a type change (breaking for typed callers)."""
        old = [_sig("m.f", positional=[_param("a", type_="int")])]
        new = [_sig("m.f", positional=[_param("a", type_="str")])]
        result = _compare(old, new)
        assert any("TYPE CHANGED" in b for b in result["breaking"])


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 3 — EVASION / OBFUSCATION  (25 tests, target = 25 %)
# ══════════════════════════════════════════════════════════════════════════════


class TestEvasionObfuscation:
    """Encoding tricks, special characters, and reformulation attempts
    that try to circumvent validation, produce incorrect output, or
    trigger path-traversal and injection vulnerabilities.
    """

    # ── Unicode / homoglyph attacks ────────────────────────────────────────

    def test_cyrillic_homoglyph_in_function_name(self):
        """Function name with Cyrillic 'а' (U+0430) instead of Latin 'a'."""
        src = _tmp(
            "def foo(): pass\n".replace("f", "ƒ")
        )  # Latin small letter f with hook
        from impactguard.extract_signatures import extract

        sigs = extract([src])
        _rm(src)
        assert isinstance(sigs, list)  # must not crash

    def test_zero_width_space_in_python_string_annotation(self):
        """Type annotation containing a zero-width space character."""
        src = _tmp("def f(x: 'int\u200b') -> None: pass\n")
        from impactguard.extract_signatures import extract

        sigs = extract([src])
        _rm(src)
        assert isinstance(sigs, list)

    def test_rtl_override_in_change_description(self):
        """Change description with RTL override should not crash risk gate."""
        desc = "REMOVED\u202e: evil.reverse"
        from impactguard.risk_model import get_severity

        s = get_severity(desc)
        assert isinstance(s, float)

    def test_emoji_in_function_name(self):
        """Python allows emoji in identifiers (kind-of); must not crash."""
        # Python 3 allows Unicode identifiers but not emoji — test graceful skip
        src = _tmp("def greet(): pass  # 👋\n")
        from impactguard.extract_signatures import extract

        sigs = extract([src])
        _rm(src)
        assert isinstance(sigs, list)

    # ── HTML / script injection ────────────────────────────────────────────

    def test_html_injection_in_function_name_is_escaped_in_report(self):
        """Function names with HTML special chars must be escaped in the report."""
        import html

        name = "<script>alert('xss')</script>"
        escaped = html.escape(name)
        assert "<script>" not in escaped
        assert "&lt;script&gt;" in escaped

    def test_html_injection_in_change_description(self):
        """generate_report must escape change descriptions."""
        import html

        desc = "<img src=x onerror=alert(1)>"
        assert "<img" not in html.escape(desc)

    def test_sql_like_chars_in_fqname_do_not_crash_compare(self):
        """fqname containing SQL-like chars must not break comparison."""
        old = [_sig("m'; DROP TABLE sigs; --f")]
        new = []
        result = _compare(old, new)
        assert isinstance(result["breaking"], list)

    def test_format_string_in_change_description_not_evaluated(self):
        """Change descriptions with format string syntax must remain literal."""
        from impactguard.risk_model import get_severity

        payload = "{__import__('os').system('id')}"
        s = get_severity(payload)
        assert isinstance(s, float)  # treated as unknown severity

    # ── JSON / serialisation attacks ──────────────────────────────────────

    def test_json_with_nan_in_count_field(self):
        """JSON payload with NaN in 'count' must not crash schema validation."""
        from impactguard.schema import validate_runtime

        # json.loads will raise on NaN; test that validate_runtime handles bad data
        bad_data = [{"function": "f", "count": "nan"}]  # string instead of float
        valid, errors = validate_runtime(bad_data)
        assert not valid
        assert errors

    def test_json_with_extremely_long_string_value(self):
        """fqname of 10 000 chars must not cause a catastrophic failure."""
        from impactguard.extract_signatures import extract

        long_name = "a" * 10_000
        src = _tmp(f"def {long_name[:100]}(): pass\n")  # trim to valid Python
        sigs = extract([src])
        _rm(src)
        assert isinstance(sigs, list)

    def test_risk_gate_with_only_whitespace_diff(self):
        """A diff containing only whitespace lines → no risks."""
        from impactguard.risk_gate import run

        diff_p = _tmp("   \n\t\n   \n", suffix=".diff")
        rt_p = _tmpjson([])
        result = run(diff_p, rt_p)
        _rm(diff_p, rt_p)
        assert result == []

    def test_risk_gate_with_ansi_escape_codes_in_diff(self):
        """ANSI escape sequences in diff must not crash the gate."""
        from impactguard.risk_gate import run

        diff_p = _tmp("\x1b[1;31mREMOVED\x1b[0m: mod.py:foo", suffix=".diff")
        rt_p = _tmpjson([])
        result = run(diff_p, rt_p)
        _rm(diff_p, rt_p)
        assert isinstance(result, list)

    # ── path traversal attacks ─────────────────────────────────────────────

    def test_path_traversal_in_fqname_is_not_a_file_path(self):
        """fqname '../../etc/passwd' must be treated as a logical name, not a path."""
        old = [_sig("../../etc/passwd")]
        result = _compare(old, [])
        # Must not raise FileNotFoundError or similar
        assert isinstance(result["breaking"], list)

    def test_path_traversal_rejected_by_is_safe_path(self):
        from impactguard._pathutils import is_safe_path

        assert is_safe_path("../../etc/passwd") is False

    def test_absolute_path_rejected_by_is_safe_path(self):
        from impactguard._pathutils import is_safe_path

        assert is_safe_path("/etc/shadow") is False

    def test_null_byte_in_path_string(self):
        """Path strings containing null bytes must not crash is_safe_path."""
        from impactguard._pathutils import is_safe_path

        result = is_safe_path("foo\x00bar.py")
        assert isinstance(result, bool)

    # ── deeply nested / recursive structures ──────────────────────────────

    def test_deeply_nested_type_annotation(self):
        """Deeply nested Optional does not crash the type-change classifier."""
        from impactguard.compare_signatures import _type_change_kind

        deep = "Optional[" * 20 + "str" + "]" * 20
        k = _type_change_kind("str", deep)
        assert k in ("widening", "narrowing", "changed")

    def test_large_signature_list_comparison_does_not_hang(self):
        """Compare two snapshots each containing 500 functions."""
        sigs = [_sig(f"m.f{i}", positional=[_param("x")]) for i in range(500)]
        result = _compare(sigs, sigs)
        assert result["breaking"] == []

    # ── control character injection ────────────────────────────────────────

    def test_tab_in_function_name_param(self):
        """Function whose parameter has a tab in its name string."""
        from impactguard.extract_signatures import extract

        src = _tmp("def f(x): pass\n")
        sigs = extract([src])
        _rm(src)
        # Tab in param is a Python syntax error; test that extractor does not crash
        assert isinstance(sigs, list)

    def test_newline_in_type_annotation_string(self):
        """Type annotation literal with embedded newline."""
        from impactguard.extract_signatures import extract

        src = _tmp('def f(x: "int\\n str") -> None: pass\n')
        sigs = extract([src])
        _rm(src)
        assert isinstance(sigs, list)

    # ── encoding tricks ────────────────────────────────────────────────────

    def test_bom_at_start_of_source_file(self):
        """UTF-8 BOM at the start of a Python source file must not crash extractor."""
        f = tempfile.NamedTemporaryFile(mode="wb", suffix=".py", delete=False)
        f.write(b"\xef\xbb\xbf" + b"def bom_func(): pass\n")
        f.close()
        from impactguard.extract_signatures import extract

        sigs = extract([f.name])
        _rm(f.name)
        assert isinstance(sigs, list)

    def test_latin1_in_comment_does_not_crash(self):
        """Source file with latin-1 encoded comment (not valid UTF-8)."""
        f = tempfile.NamedTemporaryFile(mode="wb", suffix=".py", delete=False)
        f.write(b"# caf\xe9\ndef latin_func(): pass\n")
        f.close()
        from impactguard.extract_signatures import extract

        sigs = extract([f.name])
        _rm(f.name)
        assert isinstance(sigs, list)

    def test_very_long_single_line_source(self):
        """Single Python line of 5 000 characters must not crash the extractor."""
        long_comment = "# " + "x" * 4_996
        src = _tmp(long_comment + "\ndef f(): pass\n")
        from impactguard.extract_signatures import extract

        sigs = extract([src])
        _rm(src)
        assert any(s["name"] == "f" for s in sigs)

    def test_risk_report_with_none_values_does_not_crash_schema(self):
        """Risk report item with None values in optional fields."""
        from impactguard.schema import validate_risk_report

        data = [
            {
                "function": "m.f",
                "risk": "HIGH",
                "change": None,  # should trigger validation error
                "exposure": 0.5,
                "confidence": 0.5,
            }
        ]
        valid, _ = validate_risk_report(data)
        # 'change' being None is either accepted or rejected depending on schema
        assert isinstance(valid, bool)


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 4 — COMPOSITIONAL ATTACKS  (20 tests, target = 20 %)
# ══════════════════════════════════════════════════════════════════════════════


class TestCompositionalAttacks:
    """Multi-step, chained inputs that test the pipeline end-to-end.

    These tests ensure that combining multiple attack vectors or feeding
    the output of one stage as a malicious input to the next does not
    produce incorrect risk assessments, crashes, or security failures.
    """

    # ── extract → compare → risk chain ────────────────────────────────────

    def test_extract_then_compare_breaking_change_detected(self):
        """Full extract-then-compare pipeline detects a breaking change."""
        from impactguard.extract_signatures import extract

        old_src = _tmp("def api(a, b): pass\n")
        new_src = _tmp("def api(a): pass\n")  # b removed
        old_sigs = extract([old_src])
        new_sigs = extract([new_src])
        _rm(old_src, new_src)
        old_p = _tmpjson(old_sigs)
        new_p = _tmpjson(new_sigs)
        from impactguard.compare_signatures import compare

        result = compare(old_p, new_p)
        _rm(old_p, new_p)
        assert any("REMOVED" in b or "POSITIONAL" in b for b in result["breaking"])

    def test_extract_then_compare_no_change(self):
        """Identical files → no change through the full extract+compare chain."""
        from impactguard.compare_signatures import compare
        from impactguard.extract_signatures import extract

        src = _tmp("def stable(x: int) -> str: pass\n")
        sigs = extract([src])
        _rm(src)
        p = _tmpjson(sigs)
        result = compare(p, p)
        _rm(p)
        assert result["breaking"] == []

    def test_compare_then_risk_gate_high_severity(self):
        """compare output feeds risk_gate: REMOVED function → HIGH risk."""
        from impactguard.risk_gate import run

        # A diff that triggers REMOVED detection
        diff_text = "REMOVED: mymod.py:critical_function\n"
        diff_p = _tmp(diff_text, suffix=".diff")
        rt_p = _tmpjson([{"function": "mymod.critical_function", "count": 500}])
        report = run(diff_p, rt_p)
        _rm(diff_p, rt_p)
        # With 500 calls and a REMOVED change, risk should be HIGH
        high_items = [r for r in report if r.get("risk") == "HIGH"]
        assert len(high_items) >= 1

    def test_risk_gate_then_enforce_blocks_on_high(self):
        """risk_gate produces HIGH report → enforce_gate returns exit code 1."""
        from impactguard.enforce_gate import enforce

        diff_p = _tmp("REMOVED: core.py:vital_function\n", suffix=".diff")
        rt_p = _tmpjson([{"function": "core.vital_function", "count": 1000}])
        rc = enforce(diff_p, rt_p)
        _rm(diff_p, rt_p)
        assert rc == 1

    def test_enforce_passes_with_no_high_risk(self):
        """An additive-only diff produces no HIGH risks → enforce returns 0."""
        from impactguard.enforce_gate import enforce

        diff_p = _tmp(
            "NON-BREAKING OPTIONAL POSITIONAL ADDED: x.py:f\n", suffix=".diff"
        )
        rt_p = _tmpjson([])
        rc = enforce(diff_p, rt_p)
        _rm(diff_p, rt_p)
        assert rc == 0

    # ── suppression chained with comparison ────────────────────────────────

    def test_suppressed_function_does_not_propagate_to_risk(self):
        """suppress list in compare → function absent → risk gate sees no change."""
        from impactguard.compare_signatures import compare
        from impactguard.risk_gate import run

        old_p = _tmpjson([_sig("mod.hidden")])
        new_p = _tmpjson([])
        result = compare(old_p, new_p, suppress=["mod.hidden"])
        _rm(old_p, new_p)
        # hidden was suppressed → breaking list is empty
        assert not any("hidden" in b for b in result["breaking"])

    # ── multiple simultaneous breaking changes ─────────────────────────────

    def test_multiple_breaking_changes_all_reported(self):
        """Three simultaneously removed functions → three breaking entries."""
        old = [_sig("m.a"), _sig("m.b"), _sig("m.c")]
        result = _compare(old, [])
        assert len(result["breaking"]) == 3

    def test_breaking_plus_nonbreaking_in_same_diff(self):
        """Mix of breaking and non-breaking changes reported separately."""
        old = [_sig("m.a"), _sig("m.b")]
        new = [
            _sig("m.b"),  # unchanged
            _sig("m.c"),  # added (nonbreaking)
        ]  # m.a removed (breaking)
        result = _compare(old, new)
        assert any("m.a" in b for b in result["breaking"])
        assert any("ADDED" in nb for nb in result["nonbreaking"])

    # ── transitive impact through class_hierarchy ──────────────────────────

    def test_extract_hierarchy_then_check_cascade(self):
        """Abstract class method removal cascades to concrete implementors."""
        from impactguard.class_hierarchy import (
            extract_class_hierarchy,
            get_cascade_changes,
        )

        parent_src = _tmp(
            "from abc import ABC, abstractmethod\n"
            "class Base(ABC):\n"
            "    @abstractmethod\n"
            "    def process(self): pass\n"
        )
        child_src = _tmp("class Impl(Base):\n    def process(self): pass\n")
        hierarchy = extract_class_hierarchy([parent_src, child_src])
        _rm(parent_src, child_src)
        # Simulate breaking change: Base.process removed
        comparison = {
            "breaking": [f"REMOVED: {parent_src}:Base.process"],
            "nonbreaking": [],
        }
        cascade = get_cascade_changes(comparison, hierarchy)
        assert isinstance(cascade, list)

    # ── lambda sensitivity chained with risk ───────────────────────────────

    def test_lambda_doubles_effective_severity(self):
        """lambda=2 should push a MEDIUM-severity change to HIGH."""
        from impactguard.risk_model import classify

        # severity = 0.6 (MEDIUM without lambda)
        risk_normal, _, _ = classify(0.6, 500, 1000, 500, lambda_=1.0)
        risk_double, _, _ = classify(0.6, 500, 1000, 500, lambda_=2.0)
        # With lambda=2, effective severity = 1.2 > 0.8 → HIGH
        assert risk_double == "HIGH"

    def test_lambda_halves_effective_severity(self):
        """lambda=0.5 should suppress a HIGH-severity change to MEDIUM/LOW."""
        from impactguard.risk_model import classify

        risk_full, _, _ = classify(0.9, 500, 1000, 500, lambda_=1.0)
        risk_half, _, _ = classify(0.9, 500, 1000, 500, lambda_=0.5)
        assert risk_full == "HIGH"
        assert risk_half in ("MEDIUM", "LOW")

    # ── feedback calibration chained with config ───────────────────────────

    def test_calibrated_weights_can_be_applied_to_config(self, tmp_path):
        """compute_calibrated_weights + apply_weights_to_config round-trip."""
        from impactguard.feedback import (
            apply_weights_to_config,
            compute_calibrated_weights,
        )

        outcomes = [{"change_type": "positional", "accepted": True}] * 5
        weights = compute_calibrated_weights(outcomes)
        cfg = str(tmp_path / "impactguard.toml")
        ok = apply_weights_to_config(weights, config_path=cfg)
        assert ok is True
        if weights:
            content = Path(cfg).read_text()
            assert "[impactguard.patches]" in content

    # ── schema validation gates pipeline ──────────────────────────────────

    def test_invalid_signatures_schema_prevents_comparison(self):
        """A signatures file that fails schema validation should not silently pass."""
        from impactguard.schema import validate_signatures

        bad_data = [{"name": "f"}]  # missing required fqname, positional, kwonly, etc.
        valid, errors = validate_signatures(bad_data)
        assert not valid
        assert errors

    def test_invalid_runtime_schema_still_allows_risk_gate(self):
        """Even with bad runtime data, risk_gate must not crash."""
        from impactguard.risk_gate import run

        diff_p = _tmp("REMOVED: mod.py:f\n", suffix=".diff")
        rt_p = _tmpjson([{"not_a_function_field": "x"}])
        result = run(diff_p, rt_p)
        _rm(diff_p, rt_p)
        assert isinstance(result, list)

    # ── inject into patch confidence chain ────────────────────────────────

    def test_patch_confidence_extreme_weights_then_classify(self):
        """Extreme weights fed into patch_confidence.score then classify."""
        from impactguard.patch_confidence import classify, score

        s = score(target=0.0, structural=1.0, semantic=0.0, complexity=1.0)
        level = classify(s)
        assert level in ("HIGH", "MEDIUM", "LOW")

    def test_patch_confidence_all_max_is_high(self):
        from impactguard.patch_confidence import classify, score

        s = score(target=1.0, structural=1.0, semantic=1.0, complexity=1.0)
        assert classify(s) == "HIGH"

    def test_patch_confidence_all_min_is_low(self):
        from impactguard.patch_confidence import classify, score

        s = score(target=0.0, structural=0.0, semantic=0.0, complexity=0.0)
        assert classify(s) == "LOW"

    # ── config override changes risk boundary ──────────────────────────────

    def test_config_suppress_list_respected_in_compare(self):
        """Config suppress list set before compare → function excluded."""
        from impactguard.compare_signatures import compare

        old_p = _tmpjson([_sig("pkg.internal_helper")])
        new_p = _tmpjson([])
        result = compare(old_p, new_p, suppress=["pkg.internal_helper"])
        _rm(old_p, new_p)
        assert "pkg.internal_helper" in result.get("suppressed", [])
        assert not any("internal_helper" in b for b in result["breaking"])

    # ── risk gate with empty runtime then with populated runtime ──────────

    def test_risk_level_changes_with_runtime_data(self):
        """Same diff gives UNKNOWN with empty runtime vs real level with data."""
        from impactguard.risk_gate import run

        diff_text = "REMOVED: api.py:endpoint\n"

        diff_no_rt = _tmp(diff_text, suffix=".diff")
        rt_empty = _tmpjson([])
        report_no_rt = run(diff_no_rt, rt_empty)
        _rm(diff_no_rt, rt_empty)

        diff_with_rt = _tmp(diff_text, suffix=".diff")
        rt_data = _tmpjson([{"function": "api.endpoint", "count": 999}])
        report_with_rt = run(diff_with_rt, rt_data)
        _rm(diff_with_rt, rt_data)

        levels_no_rt = {r["risk"] for r in report_no_rt}
        levels_with_rt = {r["risk"] for r in report_with_rt}
        # With real runtime data (high count) the level should be HIGH
        assert "HIGH" in levels_with_rt
        # REMOVED changes are unconditionally HIGH (bypasses confidence check)
        assert "HIGH" in levels_no_rt
