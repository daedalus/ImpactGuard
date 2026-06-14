"""Targeted tests for pipeline.py uncovered helper functions."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_validate_git_ref_empty():
    from impactguard.pipeline import _validate_git_ref

    assert _validate_git_ref("") is False
    assert _validate_git_ref("a" * 256) is False


def test_validate_git_ref_shell_chars():
    from impactguard.pipeline import _validate_git_ref

    for ch in ["|", ";", "&", "$", "`", "!", "(", ")", "<", ">"]:
        assert _validate_git_ref(f"main{ch}branch") is False, f"failed for {ch}"


def test_validate_git_ref_path_traversal():
    from impactguard.pipeline import _validate_git_ref

    assert _validate_git_ref("../../etc/passwd") is False
    assert _validate_git_ref("/absolute/path") is False


def test_validate_git_ref_invalid_chars():
    from impactguard.pipeline import _validate_git_ref

    assert _validate_git_ref("branch with space") is False
    assert _validate_git_ref("branch#hash") is False


def test_validate_git_ref_valid():
    from impactguard.pipeline import _validate_git_ref

    assert _validate_git_ref("main") is True
    assert _validate_git_ref("v1.2.3") is True
    assert _validate_git_ref("feature/my-feature") is True
    assert _validate_git_ref("origin/main") is True
    assert _validate_git_ref("a" * 255) is True


def test_validate_git_path():
    from impactguard.pipeline import _validate_git_path

    assert _validate_git_path("src/main.py") is True
    assert _validate_git_path("../escape.py") is False


def test_summarize_files_under_limit():
    from impactguard.pipeline import _summarize_files

    files = ["a.py", "b.py"]
    result = _summarize_files(files, limit=3)
    assert result == "a.py,b.py"


def test_summarize_files_over_limit():
    from impactguard.pipeline import _summarize_files

    files = ["a.py", "b.py", "c.py", "d.py"]
    result = _summarize_files(files, limit=2)
    assert "+2/4 total)" in result


def test_has_basename_collisions():
    from impactguard.pipeline import _has_basename_collisions

    assert _has_basename_collisions(["a/x.py", "b/x.py"]) is True
    assert _has_basename_collisions(["a/x.py", "b/y.py"]) is False
    assert _has_basename_collisions([]) is False


def test_compute_base_path_file(tmp_path):
    from impactguard.pipeline import _compute_base_path

    p = tmp_path / "sub" / "module.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")

    result = _compute_base_path(str(p))
    assert result == str(p.parent.resolve())


def test_compute_base_path_directory(tmp_path):
    from impactguard.pipeline import _compute_base_path

    p = tmp_path / "subdir"
    p.mkdir(parents=True, exist_ok=True)

    result = _compute_base_path(str(p) + "/")
    assert result == str(p.resolve())


def test_append_analysis_event():
    from impactguard.pipeline import _append_analysis_event

    events: list[dict] = []
    _append_analysis_event(
        events, level="error", kind="test_kind", file="f.py", message="msg"
    )
    assert len(events) == 1
    assert events[0]["level"] == "error"
    assert events[0]["kind"] == "test_kind"


def test_write_json(tmp_path):
    from impactguard.pipeline import _write_json

    out = tmp_path / "out.json"
    _write_json(out, {"key": "value"})
    assert out.exists()
    assert json.loads(out.read_text()) == {"key": "value"}


@patch("impactguard.languages.lib.registry.get_extractor")
def test_group_files_by_extractor(mock_get_extractor):
    from impactguard.pipeline import _group_files_by_extractor

    py_mock = MagicMock()
    py_mock.language = "python"
    ts_mock = MagicMock()
    ts_mock.language = "typescript"

    def side_effect(f: str):
        if f.endswith(".py"):
            return py_mock
        if f.endswith(".ts"):
            return ts_mock
        return None

    mock_get_extractor.side_effect = side_effect

    files = ["a.py", "b.ts", "c.py", "d.md"]
    groups = _group_files_by_extractor(files)

    assert "python" in groups
    assert "typescript" in groups
    assert groups["python"][1] == ["a.py", "c.py"]
    assert groups["typescript"][1] == ["b.ts"]


def test_record_unsupported_file():
    from impactguard.pipeline import _record_unsupported_file

    stats: dict[str, int] = {}
    events: list[dict] = []

    _record_unsupported_file("foo.xyz", stats, events)

    assert stats["skipped_files"] == 1
    assert stats["unsupported_files"] == 1
    assert len(events) == 1
    assert events[0]["kind"] == "unsupported_file"

    _record_unsupported_file("bar.xyz", stats, None)
    assert stats["skipped_files"] == 2


def test_record_unsupported_file_no_stats():
    from impactguard.pipeline import _record_unsupported_file

    _record_unsupported_file("foo.xyz", None, None)


def test_evaluate_analysis_policy_passes():
    from impactguard.pipeline import _evaluate_analysis_policy

    counters = {
        "parse_failures": 0,
        "skipped_files": 1,
        "call_extraction_failures": 0,
        "runtime_data_issues": 0,
    }
    policy = _evaluate_analysis_policy(
        counters,
        max_parse_failures=5,
        max_skipped_files=5,
        max_call_extraction_failures=5,
        max_runtime_data_issues=5,
    )
    assert policy["passes"] is True
    assert policy["violations"] == {}


def test_evaluate_analysis_policy_edge_boundaries():
    from impactguard.pipeline import _evaluate_analysis_policy

    counters = {
        "parse_failures": 5,
        "skipped_files": 5,
        "call_extraction_failures": 5,
        "runtime_data_issues": 5,
    }
    policy = _evaluate_analysis_policy(
        counters,
        max_parse_failures=5,
        max_skipped_files=5,
        max_call_extraction_failures=5,
        max_runtime_data_issues=5,
    )
    assert policy["passes"] is True


def test_evaluate_analysis_policy_one_over():
    from impactguard.pipeline import _evaluate_analysis_policy

    counters = {
        "parse_failures": 6,
        "skipped_files": 0,
        "call_extraction_failures": 0,
        "runtime_data_issues": 0,
    }
    policy = _evaluate_analysis_policy(
        counters,
        max_parse_failures=5,
        max_skipped_files=5,
        max_call_extraction_failures=5,
        max_runtime_data_issues=5,
    )
    assert policy["passes"] is False
    assert "parse_failures" in policy["violations"]


def test_runtime_state():
    from impactguard.pipeline import _runtime_state

    assert _runtime_state(None, {}) == "not_provided"
    assert (
        _runtime_state("/some/path", {"runtime_data_issues": 1}) == "invalid_or_missing"
    )
    assert _runtime_state("/some/path", {"runtime_data_issues": 0}) == "loaded"


def test_build_gate_reasons():
    from impactguard.pipeline import _build_gate_reasons

    policy = {
        "violations": {
            "skipped_files": {"value": 10, "max_allowed": 5},
        }
    }
    reasons = _build_gate_reasons(
        high_count=2,
        unknown_count=0,
        block_unknown=False,
        policy=policy,
        runtime_gate_blocked=False,
    )
    assert len(reasons) == 2
    assert any("HIGH" in r for r in reasons)
    assert any("skipped_files" in r for r in reasons)


def test_build_gate_reasons_block_unknown():
    from impactguard.pipeline import _build_gate_reasons

    policy = {"violations": {}}
    reasons = _build_gate_reasons(
        high_count=0,
        unknown_count=2,
        block_unknown=True,
        policy=policy,
        runtime_gate_blocked=True,
    )
    assert any("UNKNOWN" in r for r in reasons)
    assert any("runtime data" in r for r in reasons)


def test_build_gate_reasons_no_violations():
    from impactguard.pipeline import _build_gate_reasons

    policy = {"violations": {}}
    reasons = _build_gate_reasons(
        high_count=0,
        unknown_count=0,
        block_unknown=False,
        policy=policy,
        runtime_gate_blocked=False,
    )
    assert reasons == []


def test_output_patches_with_suggest(tmp_path):
    from impactguard.pipeline import _generate_patches

    fixes = [
        {"patch": "def foo(): pass", "function": "foo", "type": "add"},
        {"patch": "def bar(): pass", "function": "module:bar", "type": "modify"},
        {"not_a_patch": True},
    ]

    patches = _generate_patches(
        fixes,
        output_dir=str(tmp_path),
        suggest_patch=True,
        show_patch=True,
    )

    assert len(patches) == 2
    patch_dir = tmp_path / "patches"
    assert patch_dir.exists()
    assert (patch_dir / "patch_1.py").exists()
    assert (patch_dir / "patch_2.py").exists()


def test_output_patches_without_suggest(tmp_path):
    from impactguard.pipeline import _generate_patches

    fixes = [
        {"patch": "def foo(): pass", "function": "foo"},
    ]

    patches = _generate_patches(
        fixes,
        output_dir=str(tmp_path),
        suggest_patch=False,
        show_patch=False,
    )
    assert patches == {}


def test_output_patches_no_patches():
    from impactguard.pipeline import _generate_patches

    patches = _generate_patches(
        [{"function": "foo"}],
        output_dir="/tmp/out",
        suggest_patch=False,
        show_patch=False,
    )
    assert patches == {}


def test_output_patches_show_only(tmp_path):
    from impactguard.pipeline import _generate_patches

    with patch("builtins.print") as mock_print:
        patches = _generate_patches(
            [{"patch": "def foo(): pass", "function": "foo", "type": "add"}],
            output_dir=str(tmp_path),
            suggest_patch=False,
            show_patch=True,
        )
    assert patches == {}
    assert mock_print.call_count == 2


def test_extract_group_error(tmp_path):
    from impactguard.pipeline import _extract_group

    bad_extractor = MagicMock()
    bad_extractor.extract_signatures.side_effect = OSError("mock error")
    bad_extractor.language = "badlang"

    stats: dict[str, int] = {}
    events: list[dict] = []

    result = _extract_group(bad_extractor, ["f.py"], None, False, stats, events)
    assert result == []
    assert stats.get("parse_failures", 0) == 1


def test_extract_group_error_no_stats():
    from impactguard.pipeline import _extract_group

    bad_extractor = MagicMock()
    bad_extractor.extract_signatures.side_effect = OSError("mock error")
    bad_extractor.language = "badlang"

    result = _extract_group(bad_extractor, ["f.py"], None, False, None, None)
    assert result == []


def test_extract_group_fallback_warning():
    import warnings

    from impactguard.pipeline import _extract_group

    extractor = MagicMock()
    extractor.language = "mylang"

    def _extract(files, _base_path=None, **kw):
        warnings.warn("regex-based fallback activated")
        return [{"fqname": "test", "name": "test", "file": "f.py"}]

    extractor.extract_signatures.side_effect = _extract

    stats: dict[str, int] = {}
    events: list[dict] = []

    result = _extract_group(extractor, ["f.py"], None, False, stats, events)
    assert len(result) == 1
    assert stats.get("fallback_used", 0) == 1
    assert events[0]["kind"] == "fallback_used"


def test_extract_group_strict_support_check_error():
    from impactguard.pipeline import _extract_group

    extractor = MagicMock()
    extractor.language = "mylang"

    def broken_sig(*args, **kwargs):
        raise TypeError("not callable")

    extractor.extract_signatures = broken_sig

    stats: dict[str, int] = {}
    events: list[dict] = []

    result = _extract_group(
        extractor, ["f.py"], None, strict_extraction=True, stats=stats, events=events
    )
    assert result == []


def test_extract_python_calls_fallback_path():
    from impactguard.pipeline import _extract_python_calls

    mock_analyze = MagicMock()
    mock_analyze.side_effect = OSError("mock failure")

    all_calls: list[dict] = []
    stats: dict[str, int] = {"parse_failures": 0, "fallback_used": 0}
    events: list[dict] = []

    _extract_python_calls(
        "test.py",
        analyze_module=mock_analyze,
        all_calls=all_calls,
        stats=stats,
        events=events,
    )

    assert stats["parse_failures"] == 1
    assert stats["fallback_used"] == 1
    assert len(events) == 1
    assert events[0]["kind"] == "analyze_module_failed"


def test_extract_python_calls_fallback_and_extract_fail():
    from impactguard.pipeline import _extract_python_calls

    mock_analyze = MagicMock()
    mock_analyze.side_effect = OSError("mock failure")

    all_calls: list[dict] = []
    stats: dict[str, int] = {
        "parse_failures": 0,
        "fallback_used": 0,
        "call_extraction_failures": 0,
    }
    events: list[dict] = []

    with patch("impactguard.extract_calls.extract", side_effect=OSError("fallback also fails")):
        _extract_python_calls(
            "test.py",
            analyze_module=mock_analyze,
            all_calls=all_calls,
            stats=stats,
            events=events,
        )

    assert stats["parse_failures"] == 1
    assert stats["call_extraction_failures"] == 1


def test_extract_non_python_calls_warning():
    import warnings

    from impactguard.pipeline import _extract_non_python_calls

    extractor = MagicMock()

    def _extract_calls_with_warning(path):
        warnings.warn("regex-based fallback activated")
        return []

    extractor.extract_calls.side_effect = _extract_calls_with_warning

    all_calls: list[dict] = []
    stats: dict[str, int] = {"fallback_used": 0}
    events: list[dict] = []

    _extract_non_python_calls(
        "test.py",
        extractor=extractor,
        all_calls=all_calls,
        stats=stats,
        events=events,
    )

    assert stats["fallback_used"] == 1
    assert len(events) == 1
    assert events[0]["kind"] == "fallback_used"


def test_extract_non_python_calls_exception():
    from impactguard.pipeline import _extract_non_python_calls

    extractor = MagicMock()
    extractor.extract_calls.side_effect = OSError("extraction failure")

    all_calls: list[dict] = []
    stats: dict[str, int] = {"call_extraction_failures": 0}
    events: list[dict] = []

    _extract_non_python_calls(
        "test.py",
        extractor=extractor,
        all_calls=all_calls,
        stats=stats,
        events=events,
    )

    assert stats["call_extraction_failures"] == 1
    assert len(events) == 1
    assert events[0]["kind"] == "extract_calls_failed"


def test_attach_patch_source_info_sigs_not_found(tmp_path):
    from impactguard.pipeline import _attach_patch_source_info

    old_sigs_path = str(tmp_path / "nonexistent.json")
    risk = [{"function": "foo"}]
    stats: dict[str, int] = {"parse_failures": 0}
    events: list[dict] = []

    _attach_patch_source_info(
        risk,
        old_sigs_path=old_sigs_path,
        stats=stats,
        events=events,
        old_files=None,
    )

    assert stats.get("parse_failures", 0) == 1
    assert len(events) == 1
    assert events[0]["kind"] == "old_signatures_load_failed"


def test_attach_patch_source_info_with_mapping(tmp_path):
    from impactguard.pipeline import _attach_patch_source_info

    old_sigs = [
        {"fqname": "f.py:old_func", "name": "old_func", "file": "old_func.py"},
    ]
    old_sigs_path = tmp_path / "old.json"
    old_sigs_path.write_text(json.dumps(old_sigs))

    risk = [{"function": "f.py:old_func"}]
    stats: dict[str, int] = {"parse_failures": 0}
    events: list[dict] = []

    _attach_patch_source_info(
        risk,
        old_sigs_path=str(old_sigs_path),
        stats=stats,
        events=events,
        old_files=["/full/path/old_func.py"],
    )

    assert risk[0].get("file") == "/full/path/old_func.py"


def test_attach_patch_source_info_invalid_json(tmp_path):
    from impactguard.pipeline import _attach_patch_source_info

    old_sigs_path = tmp_path / "bad.json"
    old_sigs_path.write_text("not json")

    risk = [{"function": "foo"}]
    stats: dict[str, int] = {"parse_failures": 0}
    events: list[dict] = []

    _attach_patch_source_info(
        risk,
        old_sigs_path=str(old_sigs_path),
        stats=stats,
        events=events,
        old_files=None,
    )

    assert stats["parse_failures"] == 1


def test_calibrate_feedback_with_outcomes():
    from impactguard.pipeline import _calibrate_feedback

    stats: dict[str, int] = {"parse_failures": 0}
    events: list[dict] = []

    with (
        patch("impactguard.feedback.load_outcomes") as mock_load,
        patch("impactguard.feedback.compute_calibrated_weights") as mock_compute,
        patch("impactguard.feedback.apply_weights_to_config") as mock_apply,
    ):
        mock_load.return_value = [{"outcome": "accepted"}]
        mock_compute.return_value = {"weight": 0.8}
        _calibrate_feedback(stats, events)

        mock_compute.assert_called_once()
        mock_apply.assert_called_once_with({"weight": 0.8})


def test_calibrate_feedback_empty_outcomes():
    from impactguard.pipeline import _calibrate_feedback

    with patch("impactguard.feedback.load_outcomes", return_value=[]):
        stats: dict[str, int] = {}
        events: list[dict] = []
        _calibrate_feedback(stats, events)


def test_calibrate_feedback_import_error():
    from impactguard.pipeline import _calibrate_feedback

    stats: dict[str, int] = {}
    events: list[dict] = []

    with patch.dict("sys.modules", {"impactguard.feedback": None}):
        _calibrate_feedback(stats, events)


def test_calibrate_feedback_json_error():
    from impactguard.pipeline import _calibrate_feedback

    stats: dict[str, int] = {"parse_failures": 0}
    events: list[dict] = []

    with patch(
        "impactguard.feedback.load_outcomes",
        side_effect=json.JSONDecodeError("bad", "", 0),
    ):
        _calibrate_feedback(stats, events)

    assert stats["parse_failures"] == 1
