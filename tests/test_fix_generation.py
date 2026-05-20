import json

from impactguard.fix_generation import build_change_events
from impactguard.pipeline import run_pipeline


def _sig(
    fqname: str, file_path: str, positional: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "fqname": fqname,
        "file": file_path,
        "name": fqname.split(":")[-1],
        "positional": positional,
        "kwonly": [],
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
    assert first["fix_candidates"][0]["type"] in {"cst_patch", "text_patch"}

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
    assert "b=None" in source.read_text()
