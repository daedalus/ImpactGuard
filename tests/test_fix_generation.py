import json
from unittest.mock import patch

from impactguard.fix_generation import (
    _find_first_required_kwonly,
    _param_from_raw_change,
    _resolve_required_added_param,
    apply_safe_fixes,
    build_change_events,
    generate_fix_candidates,
)
from impactguard.pipeline import run_pipeline


def _sig(
    fqname: str, file_path: str, positional: list[dict[str, object]],
    kwonly: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "fqname": fqname,
        "file": file_path,
        "name": fqname.split(":")[-1],
        "positional": positional,
        "kwonly": kwonly or [],
        "vararg": False,
        "kwarg": False,
    }


def test_build_change_events_extracts_param_and_file(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("def foo(a, b, c):\n    return a + b + c\n")
    fqname = "mod.py:foo"
    old_sigs = [_sig(fqname, str(source), [{"name": "a", "has_default": False}])]
    new_sigs = [
        _sig(
            fqname,
            str(source),
            [
                {"name": "a", "has_default": False},
                {"name": "b", "has_default": False},
                {"name": "c", "has_default": False},
            ],
        )
    ]
    comparison = {"breaking": [f"REQUIRED_POSITIONAL_ADDED: {fqname}"]}

    events = build_change_events(comparison, old_sigs, new_sigs)
    assert len(events) == 1
    assert events[0]["function"] == fqname
    assert events[0]["change_type"] == "REQUIRED_POSITIONAL_ADDED"
    assert events[0]["param_name"] == "b"
    assert events[0]["file"] == str(source)


def test_build_change_events_required_kwonly_added(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("def foo(*, a, b):\n    pass\n")
    fqname = "mod.py:foo"
    old_sigs = [_sig(fqname, str(source), [], kwonly=[])]
    new_sigs = [
        _sig(fqname, str(source), [], kwonly=[
            {"name": "a", "has_default": False},
            {"name": "b", "has_default": False},
        ])
    ]
    comparison = {"breaking": [f"REQUIRED_KWONLY_ADDED: {fqname}"]}
    events = build_change_events(comparison, old_sigs, new_sigs)
    assert len(events) == 1
    assert events[0]["param_name"] == "a"


def test_build_change_events_skips_unparseable_line(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("def foo(a): pass\n")
    fqname = "mod.py:foo"
    sig = _sig(fqname, str(source), [])
    comparison = {"breaking": ["NOCOLON"]}
    events = build_change_events(comparison, [sig], [sig])
    assert len(events) == 0


def test_build_change_events_uses_param_from_raw_change_fallback(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("def foo(a): pass\n")
    fqname = "mod.py:foo"
    sig = _sig(fqname, str(source), [])
    comparison = {"breaking": [f"REQUIRED_POSITIONAL_ADDED: {fqname}"]}
    events = build_change_events(comparison, [sig], [sig])
    assert len(events) == 1
    assert events[0]["param_name"] is not None


def test_resolve_required_added_param_old_sig_none():
    assert _resolve_required_added_param("REQUIRED_POSITIONAL_ADDED", None, {}) is None


def test_resolve_required_added_param_new_sig_none():
    assert _resolve_required_added_param("REQUIRED_POSITIONAL_ADDED", {}, None) is None


def test_resolve_required_added_param_positional_not_list():
    result = _resolve_required_added_param(
        "REQUIRED_POSITIONAL_ADDED",
        {"positional": None, "kwonly": []},
        {"positional": [{"name": "x"}], "kwonly": []},
    )
    assert result is None


def test_resolve_required_added_param_kwonly_not_list():
    result = _resolve_required_added_param(
        "REQUIRED_POSITIONAL_ADDED",
        {"positional": [], "kwonly": None},
        {"positional": [], "kwonly": [{"name": "x"}]},
    )
    assert result is None


def test_resolve_required_added_param_unknown_change():
    result = _resolve_required_added_param(
        "UNKNOWN_CHANGE",
        {"positional": [], "kwonly": []},
        {"positional": [], "kwonly": []},
    )
    assert result is None


def test_find_first_required_kwonly_no_match():
    old = [{"name": "a"}, {"name": "b"}]
    new = [{"name": "a"}, {"name": "b"}]
    assert _find_first_required_kwonly(old, new) is None


def test_param_from_raw_change_with_arg():
    assert _param_from_raw_change("arg 'x' added to foo") == "x"


def test_param_from_raw_change_fallback():
    result = _param_from_raw_change("REQUIRED_POSITIONAL_ADDED: mod:foo")
    assert result is not None


def test_param_from_raw_change_empty():
    assert _param_from_raw_change("") is None


def test_generate_fix_candidates_empty_change_type():
    assert generate_fix_candidates({}) == []


def test_generate_fix_candidates_unsupported_change():
    assert generate_fix_candidates({"change_type": "OTHER"}) == []


def test_generate_fix_candidates_missing_fields():
    assert generate_fix_candidates({"change_type": "REQUIRED_POSITIONAL_ADDED"}) == []


def test_generate_fix_candidates_missing_file():
    assert generate_fix_candidates({
        "change_type": "REQUIRED_POSITIONAL_ADDED",
        "function": "mod:foo",
        "param_name": "x",
    }) == []


def test_generate_fix_candidates_nonexistent_file():
    assert generate_fix_candidates({
        "change_type": "REQUIRED_POSITIONAL_ADDED",
        "function": "mod:foo",
        "param_name": "x",
        "file": "/nonexistent/path.py",
    }) == []


def test_generate_fix_candidates_fallback_text_patch(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("def bar():\n    return 1\n")
    from impactguard.fix_generation import generate_fix_candidates
    result = generate_fix_candidates({
        "change_type": "REQUIRED_POSITIONAL_ADDED",
        "function": "missing_module:bar",
        "param_name": "x",
        "file": str(source),
        "lineno": 1,
    })
    assert len(result) == 1
    assert result[0]["type"] == "text_patch"





def test_apply_safe_fixes_skips_non_dict(tmp_path):
    item = {"fix_candidates": ["not_a_dict"]}
    result = apply_safe_fixes([item])
    assert result == []


def test_apply_safe_fixes_skips_non_cst_patch(tmp_path):
    item = {
        "fix_candidates": [{
            "type": "text_patch",
            "auto_applicable": True,
            "file": str(tmp_path / "x.py"),
        }]
    }
    result = apply_safe_fixes([item])
    assert result == []


def test_apply_safe_fixes_skips_not_auto_applicable(tmp_path):
    (tmp_path / "x.py").write_text("pass\n")
    item = {
        "fix_candidates": [{
            "type": "cst_patch",
            "auto_applicable": False,
            "file": str(tmp_path / "x.py"),
        }]
    }
    result = apply_safe_fixes([item])
    assert result == []


def test_apply_safe_fixes_skips_empty_file(tmp_path):
    item = {
        "fix_candidates": [{
            "type": "cst_patch",
            "auto_applicable": True,
            "file": "",
        }]
    }
    result = apply_safe_fixes([item])
    assert result == []


def test_apply_safe_fixes_multiple_fixes_skipped(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("pass\n")
    item = {
        "fix_candidates": [
            {"type": "cst_patch", "auto_applicable": True, "file": str(f), "patch": "updated"},
            {"type": "cst_patch", "auto_applicable": True, "file": str(f), "patch": "updated2"},
        ]
    }
    result = apply_safe_fixes([item])
    assert result == []


def test_apply_safe_fixes_skips_none_patch(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("pass\n")
    item = {
        "fix_candidates": [{
            "type": "cst_patch",
            "auto_applicable": True,
            "file": str(f),
            "patch": None,
        }]
    }
    result = apply_safe_fixes([item])
    assert result == []


def test_apply_safe_fixes_skips_empty_patch(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("pass\n")
    item = {
        "fix_candidates": [{
            "type": "cst_patch",
            "auto_applicable": True,
            "file": str(f),
            "patch": "",
        }]
    }
    result = apply_safe_fixes([item])
    assert result == []


def test_apply_safe_fixes_skips_nonexistent_file(tmp_path):
    item = {
        "fix_candidates": [{
            "type": "cst_patch",
            "auto_applicable": True,
            "file": str(tmp_path / "nonexistent.py"),
            "patch": "updated",
        }]
    }
    result = apply_safe_fixes([item])
    assert result == []


def test_pipeline_enriches_risk_with_fix_candidates_by_default(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("def foo(a, b):\n    return a + b\n")
    fqname = "mod.py:foo"

    old_sigs = [_sig(fqname, str(source), [{"name": "a", "has_default": False}])]
    new_sigs = [
        _sig(
            fqname,
            str(source),
            [
                {"name": "a", "has_default": False},
                {"name": "b", "has_default": False},
            ],
        )
    ]

    old_path = tmp_path / "old_sigs.json"
    new_path = tmp_path / "new_sigs.json"
    old_path.write_text(json.dumps(old_sigs))
    new_path.write_text(json.dumps(new_sigs))

    result = run_pipeline(
        old_sigs_path=str(old_path),
        new_sigs_path=str(new_path),
        output_dir=str(tmp_path / "out"),
    )

    assert result["risk"]
    first = result["risk"][0]
    assert "fix_candidates" in first
    assert first["fix_candidates"]
    assert first["fix_candidates"][0]["type"] == "cst_patch"

    risk_report = json.loads((tmp_path / "out" / "risk_report.json").read_text())
    assert risk_report[0]["fix_candidates"]


def test_pipeline_apply_safe_fixes_updates_file(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("def foo(a, b):\n    return a + b\n")
    fqname = "mod.py:foo"

    old_sigs = [_sig(fqname, str(source), [{"name": "a", "has_default": False}])]
    new_sigs = [
        _sig(
            fqname,
            str(source),
            [
                {"name": "a", "has_default": False},
                {"name": "b", "has_default": False},
            ],
        )
    ]

    old_path = tmp_path / "old_sigs.json"
    new_path = tmp_path / "new_sigs.json"
    old_path.write_text(json.dumps(old_sigs))
    new_path.write_text(json.dumps(new_sigs))

    result = run_pipeline(
        old_sigs_path=str(old_path),
        new_sigs_path=str(new_path),
        output_dir=str(tmp_path / "out_apply"),
        apply_safe_fixes=True,
    )

    assert "applied_fixes" in result
    updated = source.read_text()
    assert "b" in updated
    assert "None" in updated
