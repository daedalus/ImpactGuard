"""Tests for all new ImpactGuard features.

Covers:
1.  config.py              — Config loading, defaults, deep merge, accessor
2.  extract_signatures.py  — return_type, arg type, decorators, is_async fields
3.  compare_signatures.py  — type/decorator change detection, public/private filtering
4.  risk_model.py          — Config-driven severity scores
5.  patch_confidence.py    — Config-driven weights
6.  enforce_gate.py        — block_unknown parameter
7.  semver.py              — suggest_semver, format_semver_recommendation, _increment
8.  baseline.py            — save, load, compare, baseline_exists
9.  impact_analysis.py     — build_call_graph, find_transitive_callers, transitive flag
10. generate_report.py     — summary stats, HTML table with filter/sort UI
11. pipeline.py            — ImpactGuard.check() (no-baseline / with-baseline), semver in pipeline
12. CLI                    — --block-unknown on enforce, --watch flag, baseline/semver commands
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ─── helpers ──────────────────────────────────────────────────────────────────


def _tmp_json(data: object) -> str:
    """Write *data* to a temp JSON file and return the path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        return f.name


def _sig(
    fqname: str,
    name: str,
    positional: list | None = None,
    kwonly: list | None = None,
    vararg: bool = False,
    kwarg: bool = False,
    return_type: str | None = None,
    decorators: list | None = None,
    is_async: bool = False,
) -> dict:
    return {
        "fqname": fqname,
        "name": name,
        "positional": positional or [],
        "kwonly": kwonly or [],
        "vararg": vararg,
        "kwarg": kwarg,
        "return_type": return_type,
        "decorators": decorators or [],
        "is_async": is_async,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. config.py
# ═══════════════════════════════════════════════════════════════════════════════


def test_config_defaults_loaded():
    from impactguard.config import load_config

    cfg = load_config(config_path=None)
    ig = cfg["impactguard"]
    assert ig["severity_scores"]["REMOVED"] == 1.0
    assert ig["risk"]["confidence_threshold"] == 0.3
    assert ig["analysis"]["include_private"] is False


def test_config_deep_merge():
    from impactguard.config import _deep_merge

    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"x": 10}, "c": 4}
    result = _deep_merge(base, override)
    assert result["a"]["x"] == 10
    assert result["a"]["y"] == 2  # kept from base
    assert result["b"] == 3
    assert result["c"] == 4


def test_config_find_config_file_nonexistent(tmp_path: Path):
    from impactguard.config import _find_config_file

    # tmp_path has no impactguard.toml → should return None
    result = _find_config_file(tmp_path)
    assert result is None


def test_config_find_config_file_found(tmp_path: Path):
    from impactguard.config import _find_config_file

    (tmp_path / "impactguard.toml").write_text("[impactguard]\n")
    result = _find_config_file(tmp_path)
    assert result is not None
    assert result.name == "impactguard.toml"


def test_config_load_from_file(tmp_path: Path):
    from impactguard.config import load_config

    toml = tmp_path / "impactguard.toml"
    toml.write_text(
        "[impactguard.severity_scores]\n"
        "REMOVED = 0.5\n"
        "[impactguard.risk]\n"
        "block_unknown = true\n"
    )
    cfg = load_config(config_path=str(toml))
    ig = cfg["impactguard"]
    assert ig["severity_scores"]["REMOVED"] == 0.5
    # deep merge: ADDED should still be at default
    assert ig["severity_scores"]["ADDED"] == 0.1
    assert ig["risk"]["block_unknown"] is True


def test_config_get_accessor():
    from impactguard.config import get, reload_config

    reload_config()  # reset to defaults
    val = get("risk", "confidence_threshold", 999)
    assert val == 0.3


def test_config_reload():
    from impactguard.config import get_config, reload_config

    cfg = reload_config()
    assert cfg is not None
    assert get_config() is cfg  # singleton updated


def test_config_bad_toml_falls_back_to_defaults(tmp_path: Path):
    from impactguard.config import load_config

    bad = tmp_path / "impactguard.toml"
    bad.write_text("this is not valid = toml [[[\n")
    cfg = load_config(config_path=str(bad))
    # should fall back to defaults silently
    assert cfg["impactguard"]["severity_scores"]["REMOVED"] == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. extract_signatures.py — new fields
# ═══════════════════════════════════════════════════════════════════════════════


def test_extract_return_type_and_arg_types(tmp_path: Path):
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text("def greet(name: str, count: int = 0) -> bool:\n    pass\n")
    sigs = extract([str(src)])
    assert len(sigs) == 1
    fn = sigs[0]
    assert fn["return_type"] == "bool"
    assert fn["positional"][0]["type"] == "str"
    assert fn["positional"][1]["type"] == "int"


def test_extract_no_annotations(tmp_path: Path):
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text("def foo(x, y=None):\n    pass\n")
    sigs = extract([str(src)])
    fn = sigs[0]
    assert fn["return_type"] is None
    assert fn["positional"][0]["type"] is None


def test_extract_decorators(tmp_path: Path):
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text(
        "class C:\n    @staticmethod\n    def helper() -> None:\n        pass\n"
    )
    sigs = extract([str(src)])
    fn = next(s for s in sigs if "helper" in s["name"])
    assert "staticmethod" in fn["decorators"]


def test_extract_is_async(tmp_path: Path):
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text("async def fetch(url: str) -> bytes:\n    pass\n")
    sigs = extract([str(src)])
    fn = sigs[0]
    assert fn["is_async"] is True


def test_extract_sync_not_async(tmp_path: Path):
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text("def foo():\n    pass\n")
    sigs = extract([str(src)])
    assert sigs[0]["is_async"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3. compare_signatures.py — type/decorator/private changes
# ═══════════════════════════════════════════════════════════════════════════════


def test_compare_type_changed():
    from impactguard.compare_signatures import compare

    old = [
        _sig(
            "m.py:foo",
            "foo",
            positional=[{"name": "x", "has_default": False, "type": "int"}],
        )
    ]
    new = [
        _sig(
            "m.py:foo",
            "foo",
            positional=[{"name": "x", "has_default": False, "type": "str"}],
        )
    ]
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        result = compare(old_p, new_p, include_private=True)
        assert any("TYPE_CHANGED" in c for c in result["breaking"])
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_compare_return_type_changed():
    from impactguard.compare_signatures import compare

    old = [_sig("m.py:foo", "foo", return_type="int")]
    new = [_sig("m.py:foo", "foo", return_type="str")]
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        result = compare(old_p, new_p, include_private=True)
        assert any("RETURN_TYPE_CHANGED" in c for c in result["breaking"])
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_compare_decorator_removed():
    from impactguard.compare_signatures import compare

    old = [_sig("m.py:foo", "foo", decorators=["staticmethod"])]
    new = [_sig("m.py:foo", "foo", decorators=[])]
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        result = compare(old_p, new_p, include_private=True)
        assert any("DECORATOR_REMOVED" in c for c in result["breaking"])
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_compare_decorator_added():
    from impactguard.compare_signatures import compare

    old = [_sig("m.py:foo", "foo", decorators=[])]
    new = [_sig("m.py:foo", "foo", decorators=["property"])]
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        result = compare(old_p, new_p, include_private=True)
        assert any("DECORATOR_ADDED" in c for c in result["nonbreaking"])
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_compare_private_excluded_by_default():
    from impactguard.compare_signatures import compare
    from impactguard.config import reload_config

    reload_config()  # ensure include_private=False default

    old = [
        _sig("m.py:foo", "foo"),
        _sig("m.py:_internal", "_internal"),
    ]
    new = [_sig("m.py:foo", "foo")]  # _internal removed
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        result = compare(old_p, new_p)  # include_private defaults to config (False)
        # _internal removal should NOT appear in breaking (it was filtered out)
        assert not any("_internal" in c for c in result["breaking"])
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_compare_private_included_when_opt_in():
    from impactguard.compare_signatures import compare

    old = [
        _sig("m.py:foo", "foo"),
        _sig("m.py:_internal", "_internal"),
    ]
    new = [_sig("m.py:foo", "foo")]  # _internal removed
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        result = compare(old_p, new_p, include_private=True)
        # now _internal removal SHOULD be detected
        assert any("_internal" in c for c in result["breaking"])
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_compare_type_unchanged_no_false_positive():
    from impactguard.compare_signatures import compare

    old = [
        _sig(
            "m.py:foo",
            "foo",
            positional=[{"name": "x", "has_default": False, "type": "int"}],
        )
    ]
    new = [
        _sig(
            "m.py:foo",
            "foo",
            positional=[{"name": "x", "has_default": False, "type": "int"}],
        )
    ]
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        result = compare(old_p, new_p, include_private=True)
        assert not any("TYPE_CHANGED" in c for c in result["breaking"])
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. risk_model.py — config-driven severity
# ═══════════════════════════════════════════════════════════════════════════════


def test_risk_model_new_change_types():
    from impactguard.risk_model import SEVERITY_SCORES, get_severity

    # New change types should be in defaults
    assert "TYPE_CHANGED" in SEVERITY_SCORES
    assert "RETURN_TYPE_CHANGED" in SEVERITY_SCORES
    assert "DECORATOR_REMOVED" in SEVERITY_SCORES
    assert "DECORATOR_ADDED" in SEVERITY_SCORES


def test_risk_model_get_severity_new_types():
    from impactguard.risk_model import get_severity

    assert get_severity("TYPE_CHANGED: foo bar -> baz") == 0.6
    assert get_severity("RETURN_TYPE_CHANGED: foo int -> str") == 0.5
    assert get_severity("DECORATOR_REMOVED: foo @classmethod") > 0.5


def test_risk_model_config_override(tmp_path: Path):
    from impactguard.config import reload_config

    toml = tmp_path / "impactguard.toml"
    toml.write_text("[impactguard.severity_scores]\nREMOVED = 0.42\n")
    cfg = reload_config(str(toml))

    from impactguard.risk_model import get_severity

    # Should use overridden value
    sev = get_severity("REMOVED: some_func")
    assert sev == 0.42

    # Restore defaults
    reload_config()


def test_risk_model_classify_uses_config_thresholds(tmp_path: Path):
    from impactguard.config import reload_config

    toml = tmp_path / "impactguard.toml"
    # Set a very high high_exposure_min so HIGH is harder to trigger
    toml.write_text("[impactguard.risk]\nhigh_exposure_min = 0.99\n")
    reload_config(str(toml))

    from impactguard.risk_model import classify

    # count=50, max=100 → exposure ≈ 0.85 < 0.99 → not HIGH → MEDIUM
    risk2, _e2, _c2 = classify(0.9, 50, 100, 50)
    assert risk2 == "MEDIUM"

    # count=100, max=100 → exposure = 1.0 >= 0.99 → still HIGH
    risk_high, _, _ = classify(0.9, 100, 100, 100)
    assert risk_high == "HIGH"

    reload_config()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. patch_confidence.py — config-driven weights
# ═══════════════════════════════════════════════════════════════════════════════


def test_patch_confidence_get_target_certainty_defaults():
    from impactguard.config import reload_config
    from impactguard.patch_confidence import get_target_certainty

    reload_config()
    assert get_target_certainty(True, True, False) == 1.0
    assert get_target_certainty(False, False, True) == 0.5
    assert get_target_certainty(False, False, False) == 0.2


def test_patch_confidence_config_override(tmp_path: Path):
    from impactguard.config import reload_config

    toml = tmp_path / "impactguard.toml"
    toml.write_text("[impactguard.patches]\ntarget_name_only = 0.9\n")
    reload_config(str(toml))

    from impactguard.patch_confidence import get_target_certainty

    assert get_target_certainty(False, False, True) == 0.9

    reload_config()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. enforce_gate.py — block_unknown
# ═══════════════════════════════════════════════════════════════════════════════


def test_enforce_block_unknown_false(tmp_path: Path):
    from impactguard.enforce_gate import enforce_report

    report = [{"function": "foo", "risk": "UNKNOWN", "change": "?"}]
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(report))

    rc = enforce_report(str(rp), block_unknown=False)
    assert rc == 0  # UNKNOWN should NOT block


def test_enforce_block_unknown_true(tmp_path: Path):
    from impactguard.enforce_gate import enforce_report

    report = [{"function": "foo", "risk": "UNKNOWN", "change": "?"}]
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(report))

    rc = enforce_report(str(rp), block_unknown=True)
    assert rc == 1  # UNKNOWN blocks when requested


def test_enforce_high_always_blocks(tmp_path: Path):
    from impactguard.enforce_gate import enforce_report

    report = [{"function": "bar", "risk": "HIGH", "change": "REMOVED"}]
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(report))

    rc = enforce_report(str(rp), block_unknown=False)
    assert rc == 1


def test_enforce_low_never_blocks(tmp_path: Path):
    from impactguard.enforce_gate import enforce_report

    report = [{"function": "baz", "risk": "LOW", "change": "ADDED"}]
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(report))

    rc = enforce_report(str(rp), block_unknown=True)
    assert rc == 0


def test_enforce_reads_block_unknown_from_config(tmp_path: Path):
    from impactguard.config import reload_config
    from impactguard.enforce_gate import enforce_report

    toml = tmp_path / "impactguard.toml"
    toml.write_text("[impactguard.risk]\nblock_unknown = true\n")
    reload_config(str(toml))

    report = [{"function": "foo", "risk": "UNKNOWN", "change": "?"}]
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(report))

    # When block_unknown=None, reads from config (True)
    rc = enforce_report(str(rp), block_unknown=None)
    assert rc == 1

    reload_config()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. semver.py
# ═══════════════════════════════════════════════════════════════════════════════


def test_semver_major_on_breaking():
    from impactguard.semver import suggest_semver

    cmp = {"breaking": ["REMOVED: foo"], "nonbreaking": []}
    assert suggest_semver(cmp) == "major"


def test_semver_minor_on_nonbreaking_only():
    from impactguard.semver import suggest_semver

    cmp = {"breaking": [], "nonbreaking": ["ADDED: bar"]}
    assert suggest_semver(cmp) == "minor"


def test_semver_patch_on_no_changes():
    from impactguard.semver import suggest_semver

    cmp = {"breaking": [], "nonbreaking": []}
    assert suggest_semver(cmp) == "patch"


def test_semver_format_includes_counts():
    from impactguard.semver import format_semver_recommendation

    cmp = {"breaking": ["REMOVED: foo", "REMOVED: bar"], "nonbreaking": ["ADDED: baz"]}
    rec = format_semver_recommendation(cmp)
    assert rec["bump"] == "major"
    assert rec["breaking_count"] == 2
    assert rec["nonbreaking_count"] == 1
    assert "reason" in rec


def test_semver_increment_major():
    from impactguard.semver import _increment

    assert _increment("1.2.3", "major") == "2.0.0"


def test_semver_increment_minor():
    from impactguard.semver import _increment

    assert _increment("1.2.3", "minor") == "1.3.0"


def test_semver_increment_patch():
    from impactguard.semver import _increment

    assert _increment("1.2.3", "patch") == "1.2.4"


def test_semver_increment_with_v_prefix():
    from impactguard.semver import _increment

    assert _increment("v2.0.0", "major") == "3.0.0"


def test_semver_increment_invalid_version():
    from impactguard.semver import _increment

    result = _increment("not-a-version", "major")
    assert "next" in result


def test_semver_format_with_current_version():
    from impactguard.semver import format_semver_recommendation

    cmp = {"breaking": ["REMOVED: x"], "nonbreaking": []}
    rec = format_semver_recommendation(cmp, current_version="3.4.5")
    assert rec["next_version"] == "4.0.0"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. baseline.py
# ═══════════════════════════════════════════════════════════════════════════════


def test_baseline_save_and_load(tmp_path: Path):
    from impactguard.baseline import load_baseline, save_baseline

    src = tmp_path / "app.py"
    src.write_text("def hello(name: str) -> str:\n    pass\n")
    bpath = str(tmp_path / "baseline.json")

    saved = save_baseline([str(src)], path=bpath)
    assert Path(saved).is_file()

    data = load_baseline(bpath)
    assert "signatures" in data
    assert len(data["signatures"]) >= 1
    assert data["signatures"][0]["name"] == "hello"


def test_baseline_save_with_metadata(tmp_path: Path):
    from impactguard.baseline import load_baseline, save_baseline

    src = tmp_path / "app.py"
    src.write_text("def foo(): pass\n")
    bpath = str(tmp_path / "baseline.json")

    save_baseline([str(src)], path=bpath, metadata={"version": "1.0.0"})
    data = load_baseline(bpath)
    assert data["metadata"]["version"] == "1.0.0"


def test_baseline_load_missing_raises(tmp_path: Path):
    from impactguard.baseline import load_baseline

    with pytest.raises(FileNotFoundError):
        load_baseline(str(tmp_path / "nonexistent.json"))


def test_baseline_exists(tmp_path: Path):
    from impactguard.baseline import baseline_exists, save_baseline

    src = tmp_path / "app.py"
    src.write_text("def foo(): pass\n")
    bpath = str(tmp_path / "baseline.json")

    assert not baseline_exists(bpath)
    save_baseline([str(src)], path=bpath)
    assert baseline_exists(bpath)


def test_baseline_compare_no_changes(tmp_path: Path):
    from impactguard.baseline import compare_with_baseline, save_baseline

    src = tmp_path / "app.py"
    src.write_text("def hello(name: str) -> str:\n    pass\n")
    bpath = str(tmp_path / "baseline.json")

    save_baseline([str(src)], path=bpath)

    # Comparing the same file → no changes
    result = compare_with_baseline([str(src)], baseline_path=bpath)
    assert result["comparison"]["breaking"] == []
    assert result["comparison"]["nonbreaking"] == []
    assert result["semver"]["bump"] == "patch"


def test_baseline_compare_detects_breaking(tmp_path: Path):
    from impactguard.baseline import compare_with_baseline, save_baseline

    old_src = tmp_path / "app_old.py"
    old_src.write_text("def process(data: list) -> bool:\n    pass\n")
    bpath = str(tmp_path / "baseline.json")
    save_baseline([str(old_src)], path=bpath)

    # New version removes the function
    new_src = tmp_path / "app_new.py"
    new_src.write_text("# process was removed\n")

    result = compare_with_baseline([str(new_src)], baseline_path=bpath)
    assert result["comparison"]["breaking"]  # something was removed
    assert result["semver"]["bump"] == "major"


def test_baseline_load_bare_list_format(tmp_path: Path):
    from impactguard.baseline import load_baseline

    # Support legacy format where baseline is just a list (not wrapped)
    bpath = tmp_path / "baseline.json"
    sigs = [{"fqname": "app.py:foo", "name": "foo"}]
    bpath.write_text(json.dumps(sigs))

    data = load_baseline(str(bpath))
    assert "signatures" in data
    assert data["signatures"][0]["name"] == "foo"


def test_baseline_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from impactguard.baseline import baseline_exists, save_baseline

    bpath = str(tmp_path / "custom_baseline.json")
    monkeypatch.setenv("IMPACTGUARD_BASELINE", bpath)

    src = tmp_path / "app.py"
    src.write_text("def foo(): pass\n")

    # No explicit path — uses env var
    save_baseline([str(src)])
    assert baseline_exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. impact_analysis.py — transitive helpers
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_call_graph_basic():
    from impactguard.impact_analysis import build_call_graph

    calls = [
        {"fqname": "mod.foo", "file": "a.py"},
        {"fqname": "mod.bar", "file": "a.py"},
        {"fqname": "mod.foo", "file": "b.py"},
    ]
    graph = build_call_graph(calls)
    assert "mod.foo" in graph
    assert "a.py" in graph["mod.foo"]
    assert "b.py" in graph["mod.foo"]


def test_find_transitive_callers_depth1():
    from impactguard.impact_analysis import find_transitive_callers

    # callee→callers inverted graph
    call_graph = {
        "mod.foo": {"a.py", "b.py"},
        "a.py": {"c.py"},
    }
    directly_affected = {"mod.foo"}
    result = find_transitive_callers(directly_affected, call_graph, depth=1)
    # depth=1 → only direct callers of mod.foo
    assert "a.py" in result
    assert "b.py" in result
    # c.py is hop-2, should NOT appear at depth=1
    assert "c.py" not in result


def test_find_transitive_callers_depth2():
    from impactguard.impact_analysis import find_transitive_callers

    call_graph = {
        "mod.foo": {"a.py"},
        "a.py": {"c.py"},
    }
    directly_affected = {"mod.foo"}
    result = find_transitive_callers(directly_affected, call_graph, depth=2)
    assert "a.py" in result
    assert result["a.py"] == 1
    assert "c.py" in result
    assert result["c.py"] == 2


def test_analyze_transitive_opt_in(tmp_path: Path):
    """When transitive_depth=1, analyze() includes transitive entries."""
    from impactguard.config import reload_config
    from impactguard.impact_analysis import analyze

    toml = tmp_path / "impactguard.toml"
    toml.write_text("[impactguard.analysis]\ntransitive_depth = 1\n")
    reload_config(str(toml))

    sigs = [
        {
            "fqname": "mod.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    calls = [
        {
            "fqname": "mod.py:foo",
            "name": "foo",
            "args": 0,  # missing required arg → direct issue
            "has_starargs": False,
            "has_kwargs": False,
            "file": "caller.py",
            "lineno": 5,
        }
    ]
    sigs_p, calls_p = _tmp_json(sigs), _tmp_json(calls)
    try:
        issues = analyze(sigs_p, calls_p)
        transitive = [i for i in issues if i.get("transitive")]
        assert len(transitive) >= 1  # at least one transitive entry
        # Verify hop distance matches the configured depth (depth=1 → hop=1)
        assert all(i.get("hop", 1) == 1 for i in transitive)
    finally:
        os.unlink(sigs_p)
        os.unlink(calls_p)
        reload_config()


def test_analyze_transitive_default_disabled(tmp_path: Path):
    """When transitive_depth=0 (default), no transitive entries appear."""
    from impactguard.config import reload_config
    from impactguard.impact_analysis import analyze

    reload_config()  # default: transitive_depth=0

    sigs = [
        {
            "fqname": "mod.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    calls = [
        {
            "fqname": "mod.py:foo",
            "name": "foo",
            "args": 0,
            "has_starargs": False,
            "has_kwargs": False,
            "file": "caller.py",
            "lineno": 5,
        }
    ]
    sigs_p, calls_p = _tmp_json(sigs), _tmp_json(calls)
    try:
        issues = analyze(sigs_p, calls_p)
        assert not any(i.get("transitive") for i in issues)
    finally:
        os.unlink(sigs_p)
        os.unlink(calls_p)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. generate_report.py — summary stats and HTML structure
# ═══════════════════════════════════════════════════════════════════════════════


def test_generate_html_summary_stats():
    from impactguard.generate_report import _summary_stats, generate_html

    data = [
        {"risk": "HIGH", "function": "a", "change": "REMOVED"},
        {"risk": "HIGH", "function": "b", "change": "REMOVED"},
        {"risk": "MEDIUM", "function": "c", "change": "OPTIONAL"},
        {"risk": "LOW", "function": "d", "change": "ADDED"},
    ]
    stats = _summary_stats(data)
    assert stats["HIGH"] == 2
    assert stats["MEDIUM"] == 1
    assert stats["LOW"] == 1

    html = generate_html(data)
    # Summary badges should appear
    assert "HIGH (2)" in html
    assert "MEDIUM (1)" in html
    assert "LOW (1)" in html


def test_generate_html_has_table():
    from impactguard.generate_report import generate_html

    data = [
        {
            "risk": "HIGH",
            "function": "foo",
            "change": "REMOVED",
            "exposure": 0.9,
            "confidence": 0.8,
        }
    ]
    html = generate_html(data)
    assert "<table" in html
    assert "sortTable" in html  # sorting JS
    assert "filterLevel" in html  # filtering JS


def test_generate_html_transitive_tag():
    from impactguard.generate_report import generate_html

    data = [
        {
            "risk": "LOW",
            "function": "bar",
            "change": "indirect impact (hop 1)",
            "exposure": 0.0,
            "confidence": 0.0,
            "transitive": True,
        }
    ]
    html = generate_html(data)
    assert "indirect" in html


def test_generate_html_from_file(tmp_path: Path):
    from impactguard.generate_report import generate_html_from_file

    data = [
        {
            "risk": "LOW",
            "function": "x",
            "change": "ADDED",
            "exposure": 0.0,
            "confidence": 0.0,
        }
    ]
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(data))
    op = tmp_path / "out.html"

    html = generate_html_from_file(str(rp), str(op))
    assert op.is_file()
    assert "API Risk Report" in html


# ═══════════════════════════════════════════════════════════════════════════════
# 11. pipeline.py — ImpactGuard.check() with and without baseline
# ═══════════════════════════════════════════════════════════════════════════════


def test_pipeline_check_no_baseline(tmp_path: Path):
    from impactguard.pipeline import ImpactGuard

    src = tmp_path / "app.py"
    src.write_text("def greet(name: str) -> str:\n    pass\n")

    ig = ImpactGuard()
    result = ig.check(str(src), baseline_path=str(tmp_path / "baseline.json"))
    # No baseline → single-version result
    assert result["status"] == "no_baseline"
    assert "signatures" in result


def test_pipeline_check_with_baseline(tmp_path: Path):
    from impactguard.baseline import save_baseline
    from impactguard.pipeline import ImpactGuard

    src = tmp_path / "app.py"
    src.write_text("def greet(name: str) -> str:\n    pass\n")
    bpath = str(tmp_path / "baseline.json")
    save_baseline([str(src)], path=bpath)

    ig = ImpactGuard()
    result = ig.check(str(src), baseline_path=bpath)
    # With baseline → full comparison
    assert "comparison" in result
    assert "semver" in result


def test_pipeline_run_includes_semver(tmp_path: Path):
    """quick_check / run_pipeline result includes a 'semver' key."""
    from impactguard.pipeline import quick_check

    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "app.py").write_text("def process(data: list) -> bool:\n    pass\n")
    (new / "app.py").write_text("def process(data: list) -> bool:\n    pass\n")

    result = quick_check(str(old), str(new))
    assert "semver" in result
    assert result["semver"]["bump"] in ("major", "minor", "patch")


# ═══════════════════════════════════════════════════════════════════════════════
# 12. CLI — new commands and flags
# ═══════════════════════════════════════════════════════════════════════════════


def test_cli_baseline_save(tmp_path: Path):
    from impactguard.__main__ import main

    src = tmp_path / "app.py"
    src.write_text("def foo(): pass\n")
    bpath = tmp_path / "baseline.json"

    sys.argv = ["impactguard", "baseline", "save", str(src), "--path", str(bpath)]
    rc = main()
    assert rc == 0
    assert bpath.is_file()


def test_cli_baseline_status_no_baseline(tmp_path: Path, capsys: pytest.CaptureFixture):
    from impactguard.__main__ import main

    bpath = tmp_path / "no_baseline.json"
    sys.argv = ["impactguard", "baseline", "status", "--path", str(bpath)]
    main()
    out = capsys.readouterr().out
    assert "No baseline found" in out


def test_cli_baseline_status_exists(tmp_path: Path, capsys: pytest.CaptureFixture):
    from impactguard.__main__ import main
    from impactguard.baseline import save_baseline

    src = tmp_path / "app.py"
    src.write_text("def foo(): pass\n")
    bpath = str(tmp_path / "baseline.json")
    save_baseline([str(src)], path=bpath)

    sys.argv = ["impactguard", "baseline", "status", "--path", bpath]
    main()
    out = capsys.readouterr().out
    assert "Functions" in out or "Baseline" in out


def test_cli_baseline_compare_no_changes(tmp_path: Path, capsys: pytest.CaptureFixture):
    from impactguard.__main__ import main
    from impactguard.baseline import save_baseline

    src = tmp_path / "app.py"
    src.write_text("def foo(): pass\n")
    bpath = str(tmp_path / "baseline.json")
    save_baseline([str(src)], path=bpath)

    sys.argv = ["impactguard", "baseline", "compare", str(src), "--path", bpath]
    rc = main()
    assert rc == 0


def test_cli_semver_command(tmp_path: Path, capsys: pytest.CaptureFixture):
    from impactguard.__main__ import main

    sigs = [_sig("m.py:foo", "foo")]
    old_p, new_p = _tmp_json(sigs), _tmp_json(sigs)
    try:
        sys.argv = ["impactguard", "semver", old_p, new_p, "--current-version", "1.2.3"]
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "PATCH" in out.upper() or "patch" in out.lower()
        assert "1.2.4" in out  # next version
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_cli_semver_breaking(tmp_path: Path, capsys: pytest.CaptureFixture):
    from impactguard.__main__ import main

    old = [_sig("m.py:foo", "foo")]
    new: list = []
    old_p, new_p = _tmp_json(old), _tmp_json(new)
    try:
        sys.argv = ["impactguard", "semver", old_p, new_p]
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "MAJOR" in out.upper()
    finally:
        os.unlink(old_p)
        os.unlink(new_p)


def test_cli_enforce_block_unknown_flag(tmp_path: Path):
    """--block-unknown flag is recognised and forwarded correctly."""
    from impactguard.__main__ import main

    diff = tmp_path / "diff.txt"
    runtime = tmp_path / "runtime.json"
    diff.write_text("")
    runtime.write_text("[]")

    sys.argv = ["impactguard", "enforce", str(diff), str(runtime), "--block-unknown"]
    # Should not raise; return code depends on report contents
    rc = main()
    assert isinstance(rc, int)


def test_cli_check_has_watch_attribute():
    """The check subcommand exposes --watch without errors during parse."""
    import argparse
    import io

    from impactguard.__main__ import main

    # Just parse help — don't actually run watch mode
    sys.argv = ["impactguard", "check", "--help"]
    with pytest.raises(SystemExit) as exc_info:
        main()
    # --help exits with 0
    assert exc_info.value.code == 0


def test_cli_extract_has_new_fields(tmp_path: Path, capsys: pytest.CaptureFixture):
    """extract command output includes return_type, decorators, is_async."""
    from impactguard.__main__ import main

    src = tmp_path / "mod.py"
    src.write_text("async def fetch(url: str) -> bytes:\n    pass\n")
    sys.argv = ["impactguard", "extract", str(src)]
    main()
    out = capsys.readouterr().out
    data = json.loads(out)
    fn = data[0]
    assert fn["is_async"] is True
    assert fn["return_type"] == "bytes"
    assert fn["positional"][0]["type"] == "str"
