"""Tests for conservative mode: detect_uncalled_changes and pipeline integration."""

import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# load_funcs / load_calls helpers
# ---------------------------------------------------------------------------


class TestLoadFuncs:
    def test_load_funcs(self, tmp_path):
        from impactguard.impact_analysis import load_funcs

        data = [
            {"fqname": "mod.py:foo", "file": "mod.py", "lineno": 1},
            {"fqname": "mod.py:bar", "file": "mod.py", "lineno": 5},
        ]
        f = tmp_path / "sigs.json"
        f.write_text(json.dumps(data))
        result = load_funcs(str(f))
        assert "mod.py:foo" in result
        assert "mod.py:bar" in result
        assert result["mod.py:foo"]["lineno"] == 1

    def test_skips_entries_without_fqname(self, tmp_path):
        from impactguard.impact_analysis import load_funcs

        data = [
            {"fqname": "mod.py:foo", "file": "mod.py"},
            {"name": "bar", "file": "mod.py"},
        ]
        f = tmp_path / "sigs.json"
        f.write_text(json.dumps(data))
        result = load_funcs(str(f))
        assert "mod.py:foo" in result
        assert "mod.py:bar" not in result

    def test_invalid_json(self, tmp_path):
        from impactguard.impact_analysis import load_funcs

        f = tmp_path / "bad.json"
        f.write_text("not json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_funcs(str(f))

    def test_not_a_list(self, tmp_path):
        from impactguard.impact_analysis import load_funcs

        f = tmp_path / "obj.json"
        f.write_text('{"key": "val"}')
        with pytest.raises(ValueError, match="expected a JSON array"):
            load_funcs(str(f))

    def test_empty_list(self, tmp_path):
        from impactguard.impact_analysis import load_funcs

        f = tmp_path / "empty.json"
        f.write_text("[]")
        result = load_funcs(str(f))
        assert result == {}

    def test_file_not_found(self):
        from impactguard.impact_analysis import load_funcs

        with pytest.raises(FileNotFoundError):
            load_funcs("/nonexistent/sigs.json")


class TestLoadCalls:
    def test_load_calls(self, tmp_path):
        from impactguard.impact_analysis import load_calls

        data = [
            {"fqname": "mod.py:foo", "file": "main.py", "lineno": 3},
            {"fqname": "mod.py:bar", "file": "main.py", "lineno": 7},
        ]
        f = tmp_path / "calls.json"
        f.write_text(json.dumps(data))
        result = load_calls(str(f))
        assert len(result) == 2

    def test_skips_non_dict(self, tmp_path):
        from impactguard.impact_analysis import load_calls

        data = [
            {"fqname": "mod.py:foo"},
            "string_entry",
            42,
        ]
        f = tmp_path / "calls.json"
        f.write_text(json.dumps(data))
        result = load_calls(str(f))
        assert len(result) == 1

    def test_invalid_json(self, tmp_path):
        from impactguard.impact_analysis import load_calls

        f = tmp_path / "bad.json"
        f.write_text("not json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_calls(str(f))

    def test_not_a_list(self, tmp_path):
        from impactguard.impact_analysis import load_calls

        f = tmp_path / "obj.json"
        f.write_text('{"key": "val"}')
        with pytest.raises(ValueError, match="expected a JSON array"):
            load_calls(str(f))

    def test_empty_list(self, tmp_path):
        from impactguard.impact_analysis import load_calls

        f = tmp_path / "empty.json"
        f.write_text("[]")
        result = load_calls(str(f))
        assert result == []


# ---------------------------------------------------------------------------
# detect_uncalled_changes
# ---------------------------------------------------------------------------


class TestDetectUncalledChanges:
    def test_uncalled_function_detected(self):
        from impactguard.impact_analysis import detect_uncalled_changes

        breaking = ["REMOVED: mod.py:old_func"]
        funcs = {
            "mod.py:old_func": {
                "fqname": "mod.py:old_func",
                "file": "mod.py",
                "lineno": 1,
            }
        }
        calls = []
        issues = detect_uncalled_changes(breaking, funcs, calls)
        assert len(issues) == 1
        assert issues[0]["function"] == "mod.py:old_func"
        assert issues[0]["risk"] == "UNKNOWN"
        assert issues[0]["no_call_sites"] is True

    def test_called_function_skipped(self):
        from impactguard.impact_analysis import detect_uncalled_changes

        breaking = ["REMOVED: mod.py:active_func"]
        funcs = {
            "mod.py:active_func": {
                "fqname": "mod.py:active_func",
                "file": "mod.py",
                "lineno": 1,
            }
        }
        calls = [{"fqname": "mod.py:active_func", "file": "caller.py", "lineno": 5}]
        issues = detect_uncalled_changes(breaking, funcs, calls)
        assert issues == []

    def test_function_not_in_funcs_skipped(self):
        from impactguard.impact_analysis import detect_uncalled_changes

        breaking = ["REMOVED: mod.py:unknown"]
        funcs = {}
        calls = []
        issues = detect_uncalled_changes(breaking, funcs, calls)
        assert issues == []

    def test_malformed_breaking_line_skipped(self):
        from impactguard.impact_analysis import detect_uncalled_changes

        breaking = ["INVALID_FORMAT"]
        funcs = {"mod.py:foo": {"fqname": "mod.py:foo"}}
        calls = []
        issues = detect_uncalled_changes(breaking, funcs, calls)
        assert issues == []

    def test_resolve_target_match_skips(self):
        from impactguard.impact_analysis import detect_uncalled_changes

        breaking = ["CHANGED_ARGS: mod.py:helper"]
        funcs = {
            "mod.py:helper": {
                "fqname": "mod.py:helper",
                "file": "mod.py",
                "lineno": 1,
            }
        }
        calls = [{"fqname": "mod.py:helper"}]
        issues = detect_uncalled_changes(breaking, funcs, calls)
        assert issues == []

    def test_multiple_breaking_changes(self):
        from impactguard.impact_analysis import detect_uncalled_changes

        breaking = [
            "REMOVED: mod.py:removed_func",
            "CHANGED: mod.py:changed_func",
            "REMOVED: mod.py:called_func",
        ]
        funcs = {
            "mod.py:removed_func": {
                "fqname": "mod.py:removed_func",
                "file": "mod.py",
                "lineno": 1,
            },
            "mod.py:changed_func": {
                "fqname": "mod.py:changed_func",
                "file": "mod.py",
                "lineno": 5,
            },
            "mod.py:called_func": {
                "fqname": "mod.py:called_func",
                "file": "mod.py",
                "lineno": 10,
            },
        }
        calls = [{"fqname": "mod.py:called_func", "file": "caller.py"}]
        issues = detect_uncalled_changes(breaking, funcs, calls)
        assert len(issues) == 2
        fqnames = {i["function"] for i in issues}
        assert "mod.py:removed_func" in fqnames
        assert "mod.py:changed_func" in fqnames
        assert "mod.py:called_func" not in fqnames


# ---------------------------------------------------------------------------
# Pipeline conservative mode integration
# ---------------------------------------------------------------------------


class TestPipelineConservative:
    def test_conservative_injects_unknown_issues(self, tmp_path):
        from impactguard.pipeline import run_pipeline

        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        old_src = old_dir / "mod.py"
        old_src.write_text(textwrap.dedent("""\
            def helper():
                return 1
        """))

        new_src = new_dir / "mod.py"
        new_src.write_text(textwrap.dedent("""\
            def helper(x):
                return x + 1
        """))

        calls_dir = tmp_path / "calls"
        calls_dir.mkdir()
        calls_file = calls_dir / "calls.json"
        calls_file.write_text("[]")

        result = run_pipeline(
            old_files=[str(old_src)],
            new_files=[str(new_src)],
            calls_path=str(calls_file),
            output_dir=str(tmp_path / "out"),
            conservative=True,
        )

        impact = result.get("impact", [])
        unknown_with_no_calls = [
            i for i in impact if i.get("no_call_sites") and i["risk"] == "UNKNOWN"
        ]
        assert any("helper" in i["function"] for i in unknown_with_no_calls)

    def test_conservative_false_does_not_inject(self, tmp_path):
        from impactguard.pipeline import run_pipeline

        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        old_src = old_dir / "mod.py"
        old_src.write_text(textwrap.dedent("""\
            def helper():
                return 1
        """))

        new_src = new_dir / "mod.py"
        new_src.write_text(textwrap.dedent("""\
            def helper(x):
                return x + 1
        """))

        calls_dir = tmp_path / "calls"
        calls_dir.mkdir()
        calls_file = calls_dir / "calls.json"
        calls_file.write_text("[]")

        result = run_pipeline(
            old_files=[str(old_src)],
            new_files=[str(new_src)],
            calls_path=str(calls_file),
            output_dir=str(tmp_path / "out"),
            conservative=False,
        )

        impact = result.get("impact", [])
        unknown_with_no_calls = [
            i for i in impact if i.get("no_call_sites") and i["risk"] == "UNKNOWN"
        ]
        assert not unknown_with_no_calls

    def test_conservative_none_falls_back_to_config(self, tmp_path):
        from impactguard.pipeline import run_pipeline

        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        old_src = old_dir / "mod.py"
        old_src.write_text(textwrap.dedent("""\
            def helper():
                return 1
        """))

        new_src = new_dir / "mod.py"
        new_src.write_text(textwrap.dedent("""\
            def helper(x):
                return x + 1
        """))

        calls_dir = tmp_path / "calls"
        calls_dir.mkdir()
        calls_file = calls_dir / "calls.json"
        calls_file.write_text("[]")

        config = {"risk": {"conservative_mode": True}}
        result = run_pipeline(
            old_files=[str(old_src)],
            new_files=[str(new_src)],
            calls_path=str(calls_file),
            output_dir=str(tmp_path / "out"),
            conservative=None,
            config=config,
        )

        impact = result.get("impact", [])
        unknown_with_no_calls = [
            i for i in impact if i.get("no_call_sites") and i["risk"] == "UNKNOWN"
        ]
        assert any("helper" in i["function"] for i in unknown_with_no_calls)

    def test_conservative_with_no_breaking_changes(self, tmp_path):
        from impactguard.pipeline import run_pipeline

        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        src = textwrap.dedent("""\
            def helper():
                return 1
        """)

        old_src = old_dir / "mod.py"
        old_src.write_text(src)
        new_src = new_dir / "mod.py"
        new_src.write_text(src)

        calls_dir = tmp_path / "calls"
        calls_dir.mkdir()
        calls_file = calls_dir / "calls.json"
        calls_file.write_text("[]")

        result = run_pipeline(
            old_files=[str(old_src)],
            new_files=[str(new_src)],
            calls_path=str(calls_file),
            output_dir=str(tmp_path / "out"),
            conservative=True,
        )

        impact = result.get("impact", [])
        unknown_with_no_calls = [
            i for i in impact if i.get("no_call_sites") and i["risk"] == "UNKNOWN"
        ]
        assert not unknown_with_no_calls
