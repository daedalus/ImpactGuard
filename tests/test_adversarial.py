"""Adversarial tests for ImpactGuard.

These tests exercise each public module with malformed, boundary, and
hostile inputs to verify that the tool degrades gracefully rather than
crashing or producing silently incorrect results.
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── helpers ───────────────────────────────────────────────────────────────────

def _write_tmp(content: str, suffix: str = ".py") -> str:
    """Write *content* to a named temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        return f.name


def _write_tmp_json(data: object) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f)
        return f.name


def _write_tmp_bytes(data: bytes, suffix: str = ".json") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        return f.name


# ═══════════════════════════════════════════════════════════════════════════════
# 1. extract_signatures — adversarial Python source
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractSignaturesAdversarial:
    """Feed hostile Python source to extract_signatures.extract()."""

    def _extract(self, *paths):
        from impactguard.extract_signatures import extract
        return extract(list(paths))

    # ------------------------------------------------------------------
    # 1a. Files that cannot be parsed
    # ------------------------------------------------------------------

    def test_syntax_error_returns_empty(self):
        """A file with a syntax error must be silently skipped."""
        p = _write_tmp("def foo(\n  !!!broken syntax\n")
        try:
            result = self._extract(p)
            assert result == [], "Syntax errors should be silently skipped"
        finally:
            os.unlink(p)

    def test_completely_empty_file(self):
        p = _write_tmp("")
        try:
            assert self._extract(p) == []
        finally:
            os.unlink(p)

    def test_binary_junk_skipped(self):
        """A file containing arbitrary binary data must not crash the extractor."""
        p = _write_tmp_bytes(b"\x00\xff\xfe\x80binary\xff", suffix=".py")
        try:
            result = self._extract(p)
            assert isinstance(result, list)
        finally:
            os.unlink(p)

    def test_nonexistent_file_skipped(self):
        result = self._extract("/nonexistent/__does_not_exist__.py")
        assert result == []

    def test_path_traversal_silently_fails(self):
        result = self._extract("../../../../../../etc/passwd")
        assert result == []

    # ------------------------------------------------------------------
    # 1b. Pathological-but-valid Python
    # ------------------------------------------------------------------

    def test_function_with_1000_parameters(self):
        """A function with hundreds of parameters should not crash or OOM."""
        params = ", ".join(f"a{i}=None" for i in range(1000))
        code = f"def huge({params}): pass"
        p = _write_tmp(code)
        try:
            result = self._extract(p)
            assert len(result) == 1
            assert len(result[0]["positional"]) == 1000
        finally:
            os.unlink(p)

    def test_very_long_function_name(self):
        name = "f" * 10_000
        p = _write_tmp(f"def {name}(): pass")
        try:
            result = self._extract(p)
            assert len(result) == 1
            assert result[0]["name"] == name
        finally:
            os.unlink(p)

    def test_deeply_nested_functions(self):
        """Functions nested 50 levels deep should all be extracted."""
        depth = 50
        code = "\n".join(
            ["def level_0():"] + [f"{'  ' * (i+1)}def level_{i+1}():" for i in range(depth)] +
            [f"{'  ' * (depth+1)}pass"]
        )
        p = _write_tmp(code)
        try:
            result = self._extract(p)
            assert len(result) == depth + 1
        finally:
            os.unlink(p)

    def test_unicode_function_name(self):
        """Function names with unicode characters are valid Python 3 identifiers."""
        p = _write_tmp("def héllo_wörld(ñ=1): pass")
        try:
            result = self._extract(p)
            assert len(result) == 1
            assert "héllo_wörld" in result[0]["name"]
        finally:
            os.unlink(p)

    def test_unicode_annotation(self):
        p = _write_tmp("def f(x: 'スペシャル') -> 'テスト': pass")
        try:
            result = self._extract(p)
            assert len(result) == 1
        finally:
            os.unlink(p)

    def test_async_function_extracted(self):
        p = _write_tmp("async def fetch(url: str) -> bytes: ...")
        try:
            result = self._extract(p)
            assert len(result) == 1
            assert result[0]["is_async"] is True
        finally:
            os.unlink(p)

    def test_class_with_no_methods_returns_empty(self):
        p = _write_tmp("class Empty:\n    x = 1\n")
        try:
            result = self._extract(p)
            assert result == []
        finally:
            os.unlink(p)

    def test_deeply_nested_class_inside_function(self):
        """Class defined inside a function should still extract its methods."""
        code = (
            "def outer():\n"
            "    class Inner:\n"
            "        def method(self): pass\n"
        )
        p = _write_tmp(code)
        try:
            result = self._extract(p)
            names = [r["name"] for r in result]
            assert "outer" in names
            # method should be extracted with class context
            assert any("method" in n for n in names)
        finally:
            os.unlink(p)

    def test_decorator_with_complex_expression(self):
        """Decorators using complex call expressions must not crash serialisation."""
        code = (
            "import functools\n"
            "@functools.lru_cache(maxsize=None)\n"
            "def cached(x): return x\n"
        )
        p = _write_tmp(code)
        try:
            result = self._extract(p)
            assert len(result) == 1
            assert result[0]["decorators"] != []
        finally:
            os.unlink(p)

    def test_extract_empty_list(self):
        """extract([]) must return []."""
        from impactguard.extract_signatures import extract
        assert extract([]) == []

    def test_only_comments_no_functions(self):
        p = _write_tmp("# just a comment\n# another line\n")
        try:
            from impactguard.extract_signatures import extract
            assert extract([p]) == []
        finally:
            os.unlink(p)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. compare_signatures — adversarial JSON inputs
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompareSignaturesAdversarial:
    """Feed malformed JSON to compare_signatures.compare()."""

    def _compare(self, old_data, new_data, **kwargs):
        from impactguard.compare_signatures import compare
        old_p = _write_tmp_json(old_data)
        new_p = _write_tmp_json(new_data)
        try:
            return compare(old_p, new_p, **kwargs)
        finally:
            os.unlink(old_p)
            os.unlink(new_p)

    def _mk_sig(self, fqname, positional=None, kwonly=None, vararg=False, kwarg=False, **extra):
        return {
            "fqname": fqname,
            "name": fqname.split(":")[-1],
            "positional": positional or [],
            "kwonly": kwonly or [],
            "vararg": vararg,
            "kwarg": kwarg,
            **extra,
        }

    # ------------------------------------------------------------------
    # 2a. Corrupt / invalid JSON files
    # ------------------------------------------------------------------

    def test_corrupted_old_file_raises(self):
        """Non-JSON old file should raise an error (no silent swallow)."""
        bad_p = _write_tmp("this is not json", suffix=".json")
        good_p = _write_tmp_json([])
        from impactguard.compare_signatures import compare
        try:
            with pytest.raises(Exception):
                compare(bad_p, good_p)
        finally:
            os.unlink(bad_p)
            os.unlink(good_p)

    def test_corrupted_new_file_raises(self):
        good_p = _write_tmp_json([])
        bad_p = _write_tmp("{{invalid}", suffix=".json")
        from impactguard.compare_signatures import compare
        try:
            with pytest.raises(Exception):
                compare(good_p, bad_p)
        finally:
            os.unlink(good_p)
            os.unlink(bad_p)

    def test_nonexistent_old_path_raises(self):
        from impactguard.compare_signatures import compare
        good_p = _write_tmp_json([])
        try:
            with pytest.raises(Exception):
                compare("/no/such/file.json", good_p)
        finally:
            os.unlink(good_p)

    def test_nonexistent_new_path_raises(self):
        from impactguard.compare_signatures import compare
        good_p = _write_tmp_json([])
        try:
            with pytest.raises(Exception):
                compare(good_p, "/no/such/file.json")
        finally:
            os.unlink(good_p)

    # ------------------------------------------------------------------
    # 2b. Both empty
    # ------------------------------------------------------------------

    def test_both_empty_snapshots(self):
        result = self._compare([], [])
        assert result["breaking"] == []
        assert result["nonbreaking"] == []

    # ------------------------------------------------------------------
    # 2c. Duplicate fqnames (last one wins in dict comprehension)
    # ------------------------------------------------------------------

    def test_duplicate_fqnames_in_snapshot(self):
        """Duplicate fqnames in a snapshot must not crash."""
        sig = self._mk_sig("test.py:foo")
        result = self._compare([sig, sig], [sig])
        assert isinstance(result["breaking"], list)

    # ------------------------------------------------------------------
    # 2d. Missing required keys in signature dicts
    # ------------------------------------------------------------------

    def test_missing_positional_key_does_not_crash(self):
        """Signatures missing 'positional' should raise KeyError, not silently mangle."""
        bad_sig = {"fqname": "t.py:bad", "name": "bad", "kwonly": [], "vararg": False, "kwarg": False}
        with pytest.raises(Exception):
            self._compare([bad_sig], [bad_sig])

    # ------------------------------------------------------------------
    # 2e. Function name contains colon — adversarial fqname parsing
    # ------------------------------------------------------------------

    def test_colon_in_function_name(self):
        """A colon in a function name should not confuse the tool."""
        # This is technically illegal Python but let's check the data layer.
        sig_old = self._mk_sig("m.py:looks:weird")
        sig_new = self._mk_sig("m.py:looks:weird")
        result = self._compare([sig_old], [sig_new])
        # No change — both snapshots identical
        assert result["breaking"] == []

    # ------------------------------------------------------------------
    # 2f. Private filter
    # ------------------------------------------------------------------

    def test_private_functions_excluded_by_default(self):
        priv = self._mk_sig("m.py:_private")
        pub = self._mk_sig("m.py:public")
        # Remove private function — should not appear in breaking changes
        result = self._compare([priv, pub], [pub])
        assert all("_private" not in b for b in result["breaking"])

    def test_private_functions_included_when_asked(self):
        priv = self._mk_sig("m.py:_private")
        result = self._compare([priv], [], include_private=True)
        assert any("_private" in b for b in result["breaking"])

    # ------------------------------------------------------------------
    # 2g. Type-change edge cases
    # ------------------------------------------------------------------

    def test_type_change_from_none_to_something_not_breaking(self):
        """Adding a type annotation where none existed is not a breaking change."""
        old = self._mk_sig(
            "m.py:foo",
            positional=[{"name": "x", "has_default": False, "type": None}],
        )
        new = self._mk_sig(
            "m.py:foo",
            positional=[{"name": "x", "has_default": False, "type": "int"}],
        )
        result = self._compare([old], [new])
        # None -> something: no TYPE CHANGED reported (one side is None)
        assert not any("TYPE CHANGED" in b for b in result["breaking"])

    def test_type_change_both_sides_is_breaking(self):
        old = self._mk_sig(
            "m.py:foo",
            positional=[{"name": "x", "has_default": False, "type": "int"}],
        )
        new = self._mk_sig(
            "m.py:foo",
            positional=[{"name": "x", "has_default": False, "type": "str"}],
        )
        result = self._compare([old], [new])
        assert any("TYPE CHANGED" in b for b in result["breaking"])

    # ------------------------------------------------------------------
    # 2h. Decorator adversarial inputs
    # ------------------------------------------------------------------

    def test_decorator_with_newline_in_name(self):
        """A decorator string containing a newline should not crash."""
        old = self._mk_sig("m.py:foo", decorators=["some_decorator\ninjected"])
        new = self._mk_sig("m.py:foo", decorators=[])
        result = self._compare([old], [new])
        # Should still detect DECORATOR REMOVED
        assert any("DECORATOR REMOVED" in b for b in result["breaking"])

    def test_many_decorators_removed_all_reported(self):
        decs = [f"dec_{i}" for i in range(20)]
        old = self._mk_sig("m.py:foo", decorators=decs)
        new = self._mk_sig("m.py:foo", decorators=[])
        result = self._compare([old], [new])
        removed = [b for b in result["breaking"] if "DECORATOR REMOVED" in b]
        assert len(removed) == 20


# ═══════════════════════════════════════════════════════════════════════════════
# 3. risk_model — boundary & invalid numeric inputs
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskModelAdversarial:
    """Boundary and extreme values for risk_model functions."""

    def test_exposure_zero_count(self):
        from impactguard.risk_model import exposure
        assert exposure(0, 100) == 0.0

    def test_exposure_zero_max_with_zero_count(self):
        """exposure(0, 0) — the count==0 guard fires before the division; must return 0."""
        from impactguard.risk_model import exposure
        assert exposure(0, 0) == 0

    def test_exposure_positive_count_zero_max_raises(self):
        """exposure(1, 0) exposes a division-by-zero: log(1+0)==0 is used as divisor."""
        from impactguard.risk_model import exposure
        with pytest.raises(ZeroDivisionError):
            exposure(1, 0)

    def test_exposure_count_equals_max(self):
        from impactguard.risk_model import exposure
        assert exposure(100, 100) == 1.0

    def test_exposure_count_exceeds_max(self):
        from impactguard.risk_model import exposure
        assert exposure(9999, 100) == 1.0

    def test_exposure_very_large_counts(self):
        from impactguard.risk_model import exposure
        result = exposure(10**12, 10**12)
        assert result == 1.0

    def test_confidence_zero(self):
        from impactguard.risk_model import confidence
        assert confidence(0) == 0.0

    def test_confidence_at_threshold(self):
        from impactguard.risk_model import confidence
        assert confidence(100) == 1.0

    def test_confidence_above_threshold_clamped(self):
        from impactguard.risk_model import confidence
        assert confidence(10_000) == 1.0

    def test_confidence_negative_samples_not_clamped(self):
        """Negative sample counts are not clamped by the current implementation.

        confidence(-1) returns min(1.0, -1/100) == -0.01.  This documents
        the current (unclamped) behaviour so that any future fix is visible.
        """
        from impactguard.risk_model import confidence
        result = confidence(-1)
        assert result < 0  # current: not clamped to 0
        assert result <= 1.0  # still never above 1

    def test_classify_all_zeros(self):
        from impactguard.risk_model import classify
        risk, exp, conf = classify(0.0, 0, 0, 0)
        assert risk in ("LOW", "UNKNOWN", "MEDIUM", "HIGH")

    def test_classify_max_severity(self):
        from impactguard.risk_model import classify
        risk, _, _ = classify(1.0, 10000, 10000, 10000)
        assert risk == "HIGH"

    def test_classify_very_high_counts(self):
        from impactguard.risk_model import classify
        risk, exp, conf = classify(0.9, 10**9, 10**9, 10**9)
        assert risk == "HIGH"
        assert 0.0 <= exp <= 1.0
        assert conf == 1.0

    def test_compute_risk_zero_inputs(self):
        from impactguard.risk_model import compute_risk
        assert compute_risk(0.0, 0.0, 0.0) == 0.0

    def test_compute_risk_one_inputs(self):
        from impactguard.risk_model import compute_risk
        assert compute_risk(1.0, 1.0, 1.0) == 1.0

    def test_get_severity_empty_string(self):
        from impactguard.risk_model import get_severity
        result = get_severity("")
        assert isinstance(result, float)

    def test_get_severity_unknown_change(self):
        from impactguard.risk_model import get_severity
        assert get_severity("COMPLETELY UNKNOWN CHANGE TYPE") == 0.5

    def test_get_severity_longest_key_wins(self):
        """'RETURN TYPE CHANGED' must not match the shorter 'TYPE CHANGED' key."""
        from impactguard.risk_model import get_severity, SEVERITY_SCORES
        ret_severity = get_severity("RETURN TYPE CHANGED: m.py:foo str -> int")
        type_severity = SEVERITY_SCORES["TYPE CHANGED"]
        return_type_severity = SEVERITY_SCORES["RETURN TYPE CHANGED"]
        assert ret_severity == return_type_severity
        assert ret_severity != type_severity

    def test_get_severity_repeated_keyword(self):
        """A change type string containing a keyword multiple times must not error."""
        from impactguard.risk_model import get_severity
        result = get_severity("REMOVED REMOVED REMOVED")
        assert isinstance(result, float)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. risk_gate — adversarial diff text
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskGateAdversarial:
    """Feed hostile diff and runtime data to risk_gate.run()."""

    def _run(self, diff_text: str, runtime_data: list) -> list:
        from impactguard.risk_gate import run
        diff_p = _write_tmp(diff_text, suffix=".txt")
        rt_p = _write_tmp_json(runtime_data)
        try:
            return run(diff_p, rt_p)
        finally:
            os.unlink(diff_p)
            os.unlink(rt_p)

    def test_empty_diff_and_runtime(self):
        result = self._run("", [])
        assert result == []

    def test_diff_with_only_comments_or_noise(self):
        diff = "# This is a comment\nsome random line\n+++ new/file.py"
        result = self._run(diff, [])
        # None of these lines match breaking-change patterns
        assert result == []

    def test_diff_with_injected_colon_in_function(self):
        """A colon inside a function name part of a diff line must not crash."""
        diff = "REMOVED: m.py:Class:method_with_colon"
        result = self._run(diff, [])
        assert len(result) == 1
        assert result[0]["risk"] in ("HIGH", "MEDIUM", "LOW", "UNKNOWN")

    def test_diff_with_hundreds_of_breaking_changes(self):
        diff = "\n".join(f"REMOVED: m.py:func_{i}" for i in range(500))
        runtime = [{"function": f"func_{i}", "count": i + 1} for i in range(500)]
        result = self._run(diff, runtime)
        assert len(result) == 500

    def test_runtime_with_zero_counts(self):
        diff = "REMOVED: m.py:foo"
        result = self._run(diff, [{"function": "m.py:foo", "count": 0}])
        assert len(result) == 1

    def test_runtime_with_missing_count_key(self):
        """Runtime entries without 'count' should default gracefully."""
        diff = "REMOVED: m.py:foo"
        result = self._run(diff, [{"function": "m.py:foo"}])
        assert len(result) == 1

    def test_runtime_with_very_large_count(self):
        diff = "REMOVED: m.py:foo"
        result = self._run(diff, [{"function": "m.py:foo", "count": 10**9}])
        assert len(result) == 1
        assert 0.0 <= result[0]["exposure"] <= 1.0

    def test_nonexistent_diff_path(self):
        """Missing diff file should return empty report, not crash."""
        from impactguard.risk_gate import run
        rt_p = _write_tmp_json([])
        try:
            result = run("/no/such/diff.txt", rt_p)
            assert result == []
        finally:
            os.unlink(rt_p)

    def test_nonexistent_runtime_path(self):
        """Missing runtime file should return a report with UNKNOWN risk."""
        from impactguard.risk_gate import run
        diff_p = _write_tmp("REMOVED: m.py:foo\n", suffix=".txt")
        try:
            result = run(diff_p, "/no/such/runtime.json")
            assert len(result) == 1
            assert result[0]["risk"] in ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
        finally:
            os.unlink(diff_p)

    def test_corrupt_runtime_json(self):
        """Corrupt runtime JSON should be ignored and not crash."""
        from impactguard.risk_gate import run
        diff_p = _write_tmp("REMOVED: m.py:foo\n", suffix=".txt")
        rt_p = _write_tmp("{not valid json}", suffix=".json")
        try:
            result = run(diff_p, rt_p)
            assert isinstance(result, list)
        finally:
            os.unlink(diff_p)
            os.unlink(rt_p)

    def test_diff_with_very_long_line(self):
        """A line with a 100 000-char function name must not crash."""
        func_name = "f" * 100_000
        diff = f"REMOVED: m.py:{func_name}"
        result = self._run(diff, [])
        assert len(result) == 1

    def test_diff_with_null_bytes(self):
        """Diff text containing null bytes should be handled without crashing."""
        diff = "REMOVED: m.py:foo\x00bar"
        result = self._run(diff, [])
        assert isinstance(result, list)

    def test_diff_with_unicode(self):
        diff = "REMOVED: m.py:héllo_wörld"
        result = self._run(diff, [])
        assert len(result) == 1

    def test_output_written_to_file(self):
        """When output_path is given, a valid JSON file must be written."""
        from impactguard.risk_gate import run
        diff_p = _write_tmp("REMOVED: m.py:foo\n", suffix=".txt")
        rt_p = _write_tmp_json([{"function": "m.py:foo", "count": 5}])
        out_p = tempfile.mktemp(suffix=".json")
        try:
            run(diff_p, rt_p, out_p)
            with open(out_p) as f:
                data = json.load(f)
            assert isinstance(data, list)
        finally:
            os.unlink(diff_p)
            os.unlink(rt_p)
            if os.path.exists(out_p):
                os.unlink(out_p)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. enforce_gate — adversarial report JSON
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnforceGateAdversarial:
    """Feed hostile data to enforce_gate.enforce_report()."""

    def _enforce(self, report_data, **kwargs):
        from impactguard.enforce_gate import enforce_report
        p = _write_tmp_json(report_data)
        try:
            return enforce_report(p, **kwargs)
        finally:
            os.unlink(p)

    def test_empty_report(self):
        assert self._enforce([]) == 0

    def test_report_with_unknown_risk_level(self):
        """An unrecognised risk string must not crash."""
        result = self._enforce([{"function": "m.py:foo", "risk": "SUPERCRITICAL"}])
        assert result == 0  # should be treated as not HIGH

    def test_report_missing_risk_key_defaults_to_low(self):
        result = self._enforce([{"function": "m.py:foo"}])
        assert result == 0

    def test_report_missing_function_key(self):
        result = self._enforce([{"risk": "HIGH"}])
        assert result == 1  # still HIGH

    def test_report_with_null_values(self):
        result = self._enforce([{"function": None, "risk": None}])
        assert result == 0

    def test_many_high_risk_items(self):
        report = [{"function": f"m.py:func_{i}", "risk": "HIGH"} for i in range(1000)]
        assert self._enforce(report) == 1

    def test_block_unknown_false(self):
        result = self._enforce([{"function": "m.py:foo", "risk": "UNKNOWN"}], block_unknown=False)
        assert result == 0

    def test_block_unknown_true(self):
        result = self._enforce([{"function": "m.py:foo", "risk": "UNKNOWN"}], block_unknown=True)
        assert result == 1

    def test_nonexistent_report_path(self):
        from impactguard.enforce_gate import enforce_report
        result = enforce_report("/no/such/report.json")
        assert result == 0  # graceful fallback

    def test_corrupt_report_json(self):
        from impactguard.enforce_gate import enforce_report
        p = _write_tmp("{not: valid}", suffix=".json")
        try:
            result = enforce_report(p)
            assert result == 0
        finally:
            os.unlink(p)

    def test_report_is_not_a_list(self):
        """A JSON object (not array) at the top level causes enforce_report to raise.

        The function iterates over the report with ``for item in report``, which
        on a dict yields string keys.  Calling ``.get()`` on a string then raises
        ``AttributeError``.  This documents the current behaviour so that any
        future defensive fix is visible.
        """
        from impactguard.enforce_gate import enforce_report
        p = _write_tmp_json({"function": "m.py:foo", "risk": "HIGH"})
        try:
            with pytest.raises(AttributeError):
                enforce_report(p)
        finally:
            os.unlink(p)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. patch_confidence — boundary values
# ═══════════════════════════════════════════════════════════════════════════════

class TestPatchConfidenceAdversarial:
    """Boundary and extreme values for patch_confidence functions."""

    def test_all_zeros(self):
        from impactguard.patch_confidence import compute_confidence
        assert compute_confidence(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_all_ones(self):
        from impactguard.patch_confidence import compute_confidence
        assert compute_confidence(1.0, 1.0, 1.0, 1.0) == 1.0

    def test_classify_boundary_high(self):
        from impactguard.patch_confidence import classify
        assert classify(0.75) == "HIGH"
        assert classify(0.749) == "MEDIUM"

    def test_classify_boundary_medium(self):
        from impactguard.patch_confidence import classify
        assert classify(0.40) == "MEDIUM"
        assert classify(0.399) == "LOW"

    def test_classify_boundary_low(self):
        from impactguard.patch_confidence import classify
        assert classify(0.20) == "LOW"
        assert classify(0.199) == "UNKNOWN"

    def test_classify_negative_value(self):
        from impactguard.patch_confidence import classify
        result = classify(-1.0)
        assert result == "UNKNOWN"

    def test_classify_above_one(self):
        from impactguard.patch_confidence import classify
        result = classify(2.0)
        assert result == "HIGH"

    def test_get_target_certainty_all_false(self):
        from impactguard.patch_confidence import get_target_certainty
        result = get_target_certainty(False, False, False)
        assert 0.0 <= result <= 1.0

    def test_get_structural_safety_empty_string(self):
        from impactguard.patch_confidence import get_structural_safety
        result = get_structural_safety("")
        assert isinstance(result, float)

    def test_get_semantic_risk_empty_string(self):
        from impactguard.patch_confidence import get_semantic_risk
        result = get_semantic_risk("")
        assert isinstance(result, float)

    def test_complexity_all_flags_set(self):
        from impactguard.patch_confidence import get_complexity_penalty
        result = get_complexity_penalty(True, True, True, True)
        assert 0.0 <= result <= 1.0

    def test_complexity_no_flags(self):
        from impactguard.patch_confidence import get_complexity_penalty
        assert get_complexity_penalty(False, False, False, False) == 1.0

    def test_classify_with_factors_all_ones(self):
        from impactguard.patch_confidence import classify_with_factors
        level, factors = classify_with_factors(1.0, 1.0, 1.0, 1.0)
        assert level == "HIGH"
        assert factors["final"] == 1.0

    def test_classify_with_factors_all_zeros(self):
        from impactguard.patch_confidence import classify_with_factors
        level, factors = classify_with_factors(0.0, 0.0, 0.0, 0.0)
        assert level == "UNKNOWN"
        assert factors["final"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. config — hostile config files
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigAdversarial:
    """Feed bad config files to config.load_config()."""

    def test_nonexistent_path_returns_defaults(self):
        from impactguard.config import load_config
        result = load_config("/no/such/impactguard.toml")
        # Should fall back to defaults
        assert "impactguard" in result

    def test_empty_toml_returns_defaults(self):
        from impactguard.config import load_config
        p = _write_tmp("", suffix=".toml")
        try:
            result = load_config(p)
            assert "impactguard" in result
        finally:
            os.unlink(p)

    def test_invalid_toml_returns_defaults(self):
        from impactguard.config import load_config
        p = _write_tmp("[[not valid toml\n", suffix=".toml")
        try:
            result = load_config(p)
            assert "impactguard" in result
        finally:
            os.unlink(p)

    def test_toml_with_extra_unknown_keys_merged(self):
        from impactguard.config import load_config
        toml_content = "[impactguard.risk]\nconfidence_threshold = 0.99\n"
        p = _write_tmp(toml_content, suffix=".toml")
        try:
            result = load_config(p)
            assert result["impactguard"]["risk"]["confidence_threshold"] == 0.99
            # Other defaults still present
            assert "high_exposure_min" in result["impactguard"]["risk"]
        finally:
            os.unlink(p)

    def test_get_with_missing_section(self):
        from impactguard.config import reload_config, get
        reload_config()
        result = get("nonexistent_section", "nonexistent_key", "default_val")
        assert result == "default_val"

    def test_singleton_reloads_cleanly(self):
        from impactguard import config as cfg_mod
        cfg_mod.reload_config()
        c1 = cfg_mod.get_config()
        cfg_mod.reload_config()
        c2 = cfg_mod.get_config()
        assert c1 == c2  # same content after two fresh loads


# ═══════════════════════════════════════════════════════════════════════════════
# 8. serialize_function — adversarial AST nodes
# ═══════════════════════════════════════════════════════════════════════════════

class TestSerializeFunctionAdversarial:
    """Directly test serialize_function with crafted AST nodes."""

    def _parse_func(self, code: str):
        import ast
        return ast.parse(code).body[0]

    def test_no_args_no_returns(self):
        from impactguard.extract_signatures import serialize_function
        node = self._parse_func("def f(): pass")
        result = serialize_function(node, "test.py")
        assert result["positional"] == []
        assert result["return_type"] is None

    def test_return_annotation_preserved(self):
        from impactguard.extract_signatures import serialize_function
        node = self._parse_func("def f() -> list[int]: pass")
        result = serialize_function(node, "test.py")
        assert result["return_type"] == "list[int]"

    def test_class_context_in_fqname(self):
        from impactguard.extract_signatures import serialize_function
        node = self._parse_func("def method(self): pass")
        result = serialize_function(node, "test.py", class_name="MyClass")
        assert result["fqname"] == "test.py:MyClass.method"
        assert result["class_name"] == "MyClass"

    def test_vararg_and_kwarg_flags(self):
        from impactguard.extract_signatures import serialize_function
        node = self._parse_func("def f(*args, **kwargs): pass")
        result = serialize_function(node, "test.py")
        assert result["vararg"] is True
        assert result["kwarg"] is True

    def test_kwonly_args(self):
        from impactguard.extract_signatures import serialize_function
        node = self._parse_func("def f(*, key=None): pass")
        result = serialize_function(node, "test.py")
        assert len(result["kwonly"]) == 1
        assert result["kwonly"][0]["name"] == "key"
        assert result["kwonly"][0]["has_default"] is True

    def test_async_flag(self):
        import ast
        from impactguard.extract_signatures import serialize_function
        code = "async def f(): pass"
        node = ast.parse(code).body[0]
        result = serialize_function(node, "test.py")
        assert result["is_async"] is True
