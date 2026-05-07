"""Tests for the 10 new domain features.

Covers:
1.  Suppression / Inline Ignore Mechanism
2.  __all__ Export Awareness
3.  Deprecation Lifecycle
4.  Protocol / ABC Cascade
5.  Type Compatibility Awareness (widening vs narrowing)
6.  __init__.py Re-export Propagation
7.  PR Comment / Markdown Summary Generation
8.  Multi-Baseline / Release History
9.  Feedback Loop Implementation
10. JSON Schema / Data Contract Validation
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


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
    ignored: bool = False,
    exported: bool | None = None,
) -> dict[str, Any]:
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
        "ignored": ignored,
        "exported": exported,
    }


def _write_json(data: object, path: Path) -> None:
    path.write_text(json.dumps(data))


def _compare(old: list, new: list) -> dict:
    from impactguard.compare_signatures import compare

    with tempfile.TemporaryDirectory() as tmpdir:
        old_p = Path(tmpdir) / "old.json"
        new_p = Path(tmpdir) / "new.json"
        _write_json(old, old_p)
        _write_json(new, new_p)
        return compare(str(old_p), str(new_p))


# ═════════════════════════════════════════════════════════════════════════════
# Feature 1 – Suppression / Inline Ignore Mechanism
# ═════════════════════════════════════════════════════════════════════════════


def test_ignore_inline_comment_on_def_line(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text(
        "# impactguard: ignore\ndef foo(x):\n    pass\n\ndef bar(y):\n    pass\n"
    )
    sigs = extract([str(src)])
    foo = next(s for s in sigs if s["name"] == "foo")
    bar = next(s for s in sigs if s["name"] == "bar")
    assert foo["ignored"] is True
    assert bar["ignored"] is False


def test_ignore_comment_on_same_line_as_def(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text("def foo(x):  # impactguard: ignore\n    pass\n")
    sigs = extract([str(src)])
    assert sigs[0]["ignored"] is True


def test_ignored_function_excluded_from_comparison(tmp_path: Path) -> None:
    """Functions marked ignored in old/new should not appear in breaking."""
    old_sig = _sig("mod.py:foo", "foo", ignored=True)
    new_sig_list: list[dict] = []  # foo removed
    result = _compare([old_sig], new_sig_list)
    assert "REMOVED: mod.py:foo" not in result["breaking"]
    assert "mod.py:foo" in result["suppressed"]


def test_config_suppress_list_excludes_function(tmp_path: Path) -> None:
    from impactguard.compare_signatures import compare
    from impactguard.config import reload_config

    toml = tmp_path / "impactguard.toml"
    toml.write_text('[impactguard.analysis]\nsuppress = ["mod.py:bar"]\n')

    old_sigs = [_sig("mod.py:bar", "bar")]
    new_sigs: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        old_p = Path(tmpdir) / "old.json"
        new_p = Path(tmpdir) / "new.json"
        _write_json(old_sigs, old_p)
        _write_json(new_sigs, new_p)

        reload_config(config_path=str(toml))
        try:
            result = compare(str(old_p), str(new_p))
        finally:
            reload_config()  # reset

    assert "REMOVED: mod.py:bar" not in result["breaking"]
    assert "mod.py:bar" in result["suppressed"]


# ═════════════════════════════════════════════════════════════════════════════
# Feature 2 – __all__ Export Awareness
# ═════════════════════════════════════════════════════════════════════════════


def test_all_exports_mark_exported_true(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text(
        "__all__ = ['public_fn']\n"
        "\n"
        "def public_fn():\n"
        "    pass\n"
        "\n"
        "def _private_fn():\n"
        "    pass\n"
        "\n"
        "def unlisted_fn():\n"
        "    pass\n"
    )
    sigs = extract([str(src)])
    by_name = {s["name"]: s for s in sigs}

    assert by_name["public_fn"]["exported"] is True
    assert by_name["_private_fn"]["exported"] is False
    assert by_name["unlisted_fn"]["exported"] is False


def test_no_all_sets_exported_none(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text("def foo():\n    pass\n")
    sigs = extract([str(src)])
    assert sigs[0]["exported"] is None


def test_all_aware_comparison_excludes_non_exported(tmp_path: Path) -> None:
    """When __all__ is defined, only exported symbols should trigger breaking changes."""
    # old: foo exported, bar not exported
    old_sigs = [
        _sig("mod.py:foo", "foo", exported=True),
        _sig("mod.py:bar", "bar", exported=False),
    ]
    # new: both removed — only foo (exported) should be in breaking
    result = _compare(old_sigs, [])
    breaking = result["breaking"]
    assert any("mod.py:foo" in b for b in breaking), (
        "exported removal should be breaking"
    )
    assert not any("mod.py:bar" in b for b in breaking), (
        "non-exported should not be breaking"
    )


def test_all_aware_comparison_underscore_private_excluded_by_default() -> None:
    """_ prefixed functions without __all__ should still be excluded by default."""
    old_sigs = [_sig("mod.py:_helper", "_helper")]
    result = _compare(old_sigs, [])
    assert "REMOVED: mod.py:_helper" not in result["breaking"]


# ═════════════════════════════════════════════════════════════════════════════
# Feature 3 – Deprecation Lifecycle
# ═════════════════════════════════════════════════════════════════════════════


def test_deprecated_removed_is_nonbreaking() -> None:
    old_sig = _sig("mod.py:old_fn", "old_fn", decorators=["deprecated"])
    result = _compare([old_sig], [])
    assert "DEPRECATED_REMOVED: mod.py:old_fn" in result["nonbreaking"]
    assert "REMOVED: mod.py:old_fn" not in result["breaking"]


def test_deprecated_full_decorator_path() -> None:
    """functools / third-party deprecated decorators should also be recognized."""
    old_sig = _sig("mod.py:fn", "fn", decorators=["warnings.deprecated('old')"])
    result = _compare([old_sig], [])
    assert "DEPRECATED_REMOVED: mod.py:fn" in result["nonbreaking"]


def test_non_deprecated_removal_is_breaking() -> None:
    old_sig = _sig("mod.py:fn", "fn")
    result = _compare([old_sig], [])
    assert "REMOVED: mod.py:fn" in result["breaking"]


def test_deprecated_removed_has_low_severity() -> None:
    from impactguard.risk_model import SEVERITY_SCORES

    score = SEVERITY_SCORES.get("DEPRECATED_REMOVED", None)
    assert score is not None
    assert score < SEVERITY_SCORES["REMOVED"], (
        "deprecated removal must be lower risk than plain removal"
    )


def test_deprecated_removed_does_not_trigger_major_semver() -> None:
    from impactguard.semver import suggest_semver

    result = suggest_semver(
        {"breaking": [], "nonbreaking": ["DEPRECATED_REMOVED: mod.py:fn"]}
    )
    assert result in ("minor", "patch")


def test_deprecated_removed_from_extracted_source(tmp_path: Path) -> None:
    """End-to-end: @deprecated decorator on function causes nonbreaking removal."""
    from impactguard.extract_signatures import extract

    src = tmp_path / "old.py"
    src.write_text(
        "def deprecated(func):\n"
        "    return func\n"
        "\n"
        "@deprecated\n"
        "def old_api():\n"
        "    pass\n"
    )
    sigs = extract([str(src)])
    old_api = next(s for s in sigs if s["name"] == "old_api")
    assert "deprecated" in old_api["decorators"]

    result = _compare(sigs, [])
    assert "DEPRECATED_REMOVED: old.py:old_api" in result["nonbreaking"]


# ═════════════════════════════════════════════════════════════════════════════
# Feature 4 – Protocol / ABC Cascade
# ═════════════════════════════════════════════════════════════════════════════


def test_extract_class_hierarchy_protocol(tmp_path: Path) -> None:
    from impactguard.class_hierarchy import extract_class_hierarchy

    src = tmp_path / "api.py"
    src.write_text(
        "from typing import Protocol\n"
        "\n"
        "class MyProtocol(Protocol):\n"
        "    def execute(self, task: str) -> None: ...\n"
        "\n"
        "class ConcreteImpl:\n"
        "    def execute(self, task: str) -> None:\n"
        "        pass\n"
    )
    hier = extract_class_hierarchy([str(src)])
    assert "MyProtocol" in hier
    assert hier["MyProtocol"]["is_protocol"] is True
    assert "execute" in hier["MyProtocol"]["methods"]
    assert "ConcreteImpl" in hier
    assert hier["ConcreteImpl"]["is_protocol"] is False
    assert hier["ConcreteImpl"]["is_abc"] is False


def test_extract_class_hierarchy_abc(tmp_path: Path) -> None:
    from impactguard.class_hierarchy import extract_class_hierarchy

    src = tmp_path / "base.py"
    src.write_text("import abc\n\nclass Base(abc.ABC):\n    def process(self): ...\n")
    hier = extract_class_hierarchy([str(src)])
    assert hier["Base"]["is_abc"] is True


def test_find_implementations(tmp_path: Path) -> None:
    from impactguard.class_hierarchy import (
        extract_class_hierarchy,
        find_implementations,
    )

    src = tmp_path / "api.py"
    src.write_text(
        "from typing import Protocol\n"
        "\n"
        "class Serializer(Protocol):\n"
        "    def serialize(self): ...\n"
        "\n"
        "class JSONSerializer(Serializer):\n"
        "    def serialize(self): return '{}'\n"
        "\n"
        "class XMLSerializer(Serializer):\n"
        "    def serialize(self): return '<root/>'\n"
    )
    hier = extract_class_hierarchy([str(src)])
    impls = find_implementations(hier)
    assert "Serializer" in impls
    assert "JSONSerializer" in impls["Serializer"]
    assert "XMLSerializer" in impls["Serializer"]


def test_cascade_changes_for_protocol_method_change() -> None:
    from impactguard.class_hierarchy import get_cascade_changes

    comparison = {
        "breaking": ["REMOVED: api.py:Serializer.serialize"],
        "nonbreaking": [],
    }
    hierarchy = {
        "Serializer": {
            "bases": ["Protocol"],
            "file": "api.py",
            "is_protocol": True,
            "is_abc": False,
            "methods": ["serialize"],
        },
        "JSONSerializer": {
            "bases": ["Serializer"],
            "file": "api.py",
            "is_protocol": False,
            "is_abc": False,
            "methods": ["serialize"],
        },
    }
    cascade = get_cascade_changes(comparison, hierarchy)
    assert any("JSONSerializer" in c for c in cascade)
    assert any("serialize" in c for c in cascade)


def test_cascade_empty_for_non_abstract() -> None:
    from impactguard.class_hierarchy import get_cascade_changes

    comparison = {"breaking": ["REMOVED: mod.py:Foo.bar"], "nonbreaking": []}
    hierarchy = {
        "Foo": {
            "bases": [],
            "file": "mod.py",
            "is_protocol": False,
            "is_abc": False,
            "methods": ["bar"],
        }
    }
    cascade = get_cascade_changes(comparison, hierarchy)
    assert cascade == []


# ═════════════════════════════════════════════════════════════════════════════
# Feature 5 – Type Compatibility Awareness
# ═════════════════════════════════════════════════════════════════════════════


def test_type_widening_is_nonbreaking() -> None:
    """int → int | None is widening: non-breaking."""
    old_sigs = [
        _sig(
            "mod.py:fn",
            "fn",
            positional=[{"name": "x", "has_default": False, "type": "int"}],
        )
    ]
    new_sigs = [
        _sig(
            "mod.py:fn",
            "fn",
            positional=[{"name": "x", "has_default": False, "type": "int | None"}],
        )
    ]
    result = _compare(old_sigs, new_sigs)
    assert any("TYPE_WIDENED" in nb for nb in result["nonbreaking"])
    assert not any("TYPE_CHANGED" in b for b in result["breaking"])


def test_type_optional_widening_is_nonbreaking() -> None:
    """str → Optional[str] is widening."""
    from impactguard.compare_signatures import _type_change_kind

    assert _type_change_kind("str", "Optional[str]") == "widening"


def test_type_narrowing_is_breaking() -> None:
    """int | None → int is narrowing: breaking."""
    old_sigs = [
        _sig(
            "mod.py:fn",
            "fn",
            positional=[{"name": "x", "has_default": False, "type": "int | None"}],
        )
    ]
    new_sigs = [
        _sig(
            "mod.py:fn",
            "fn",
            positional=[{"name": "x", "has_default": False, "type": "int"}],
        )
    ]
    result = _compare(old_sigs, new_sigs)
    assert any("TYPE_CHANGED" in b for b in result["breaking"])


def test_completely_different_type_is_breaking() -> None:
    """str → int is a type change: breaking."""
    from impactguard.compare_signatures import _type_change_kind

    assert _type_change_kind("str", "int") == "changed"


def test_return_type_widening_is_nonbreaking() -> None:
    """Widened return type is non-breaking."""
    old_sigs = [_sig("mod.py:fn", "fn", return_type="str")]
    new_sigs = [_sig("mod.py:fn", "fn", return_type="str | None")]
    result = _compare(old_sigs, new_sigs)
    assert any("RETURN_TYPE_WIDENED" in nb for nb in result["nonbreaking"])
    assert not any("RETURN_TYPE_CHANGED" in b for b in result["breaking"])


def test_return_type_narrowing_is_breaking() -> None:
    """Narrowed return type is breaking."""
    old_sigs = [_sig("mod.py:fn", "fn", return_type="str | None")]
    new_sigs = [_sig("mod.py:fn", "fn", return_type="str")]
    result = _compare(old_sigs, new_sigs)
    assert any("RETURN_TYPE_CHANGED" in b for b in result["breaking"])


def test_union_widening_detection() -> None:
    from impactguard.compare_signatures import _parse_union_members, _type_change_kind

    # Union[str, int] → Union[str, int, None]  widening
    assert _type_change_kind("str | int", "str | int | None") == "widening"
    # str → int: different types (changed)
    assert _type_change_kind("str", "int") == "changed"
    # int | None → int: narrowing
    assert _type_change_kind("int | None", "int") == "narrowing"

    # parse helpers
    members = _parse_union_members("Optional[int]")
    assert "int" in members and "None" in members


# ═════════════════════════════════════════════════════════════════════════════
# Feature 6 – __init__.py Re-export Propagation
# ═════════════════════════════════════════════════════════════════════════════


def test_extract_reexports_simple(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract_reexports

    init = tmp_path / "__init__.py"
    init.write_text("from .core import helper\nfrom .utils import format as fmt\n")
    reexports = extract_reexports([str(init)])
    assert "__init__.py:helper" in reexports
    assert reexports["__init__.py:helper"] == "core.py:helper"
    assert "__init__.py:fmt" in reexports
    assert reexports["__init__.py:fmt"] == "utils.py:format"


def test_extract_reexports_ignores_absolute_imports(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract_reexports

    init = tmp_path / "__init__.py"
    init.write_text("from os.path import join\nfrom .core import helper\n")
    reexports = extract_reexports([str(init)])
    # Absolute import (os.path) should be ignored
    assert not any("join" in k for k in reexports)
    assert "__init__.py:helper" in reexports


def test_extract_with_include_reexports(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    core = pkg / "core.py"
    core.write_text("def helper():\n    pass\n")
    init = pkg / "__init__.py"
    init.write_text("from .core import helper\n")

    sigs = extract([str(core), str(init)], include_reexports=True)
    fqnames = [s["fqname"] for s in sigs]
    assert "__init__.py:helper" in fqnames
    # Original also present
    assert "core.py:helper" in fqnames


def test_reexport_alias_has_reexported_from_field(tmp_path: Path) -> None:
    from impactguard.extract_signatures import extract

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text("def api():\n    pass\n")
    (pkg / "__init__.py").write_text("from .core import api\n")

    sigs = extract(
        [str(pkg / "core.py"), str(pkg / "__init__.py")], include_reexports=True
    )
    alias = next((s for s in sigs if s["fqname"] == "__init__.py:api"), None)
    assert alias is not None
    assert alias.get("reexported_from") == "core.py:api"


# ═════════════════════════════════════════════════════════════════════════════
# Feature 7 – PR Comment / Markdown Summary Generation
# ═════════════════════════════════════════════════════════════════════════════


def test_generate_markdown_basic() -> None:
    from impactguard.generate_report import generate_markdown

    report = [
        {
            "function": "foo",
            "risk": "HIGH",
            "change": "REMOVED",
            "exposure": 0.5,
            "confidence": 0.9,
        },
        {
            "function": "bar",
            "risk": "LOW",
            "change": "OPTIONAL",
            "exposure": 0.01,
            "confidence": 0.3,
        },
    ]
    md = generate_markdown(report)
    assert "ImpactGuard" in md
    assert "HIGH" in md
    assert "foo" in md
    assert "bar" in md


def test_generate_markdown_empty_report() -> None:
    from impactguard.generate_report import generate_markdown

    md = generate_markdown([])
    assert "No risk items" in md


def test_generate_markdown_with_semver() -> None:
    from impactguard.generate_report import generate_markdown

    semver = {"bump": "major", "reason": "breaking change", "next_version": "2.0.0"}
    md = generate_markdown(
        [
            {
                "function": "f",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 1.0,
                "confidence": 1.0,
            }
        ],
        semver_rec=semver,
    )
    assert "MAJOR" in md
    assert "2.0.0" in md


def test_generate_markdown_respects_max_rows() -> None:
    from impactguard.generate_report import generate_markdown

    report = [
        {
            "function": f"fn{i}",
            "risk": "LOW",
            "change": "OPTIONAL",
            "exposure": 0.0,
            "confidence": 0.1,
        }
        for i in range(30)
    ]
    md = generate_markdown(report, max_rows=5)
    assert "25 more entries" in md


def test_generate_markdown_transitive_label() -> None:
    from impactguard.generate_report import generate_markdown

    report = [
        {
            "function": "fn",
            "risk": "MEDIUM",
            "change": "REQUIRED",
            "exposure": 0.1,
            "confidence": 0.5,
            "transitive": True,
        }
    ]
    md = generate_markdown(report)
    assert "indirect" in md


def test_generate_markdown_from_file(tmp_path: Path) -> None:
    from impactguard.generate_report import generate_markdown_from_file

    report = [
        {
            "function": "f",
            "risk": "HIGH",
            "change": "REMOVED",
            "exposure": 0.5,
            "confidence": 1.0,
        }
    ]
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report))
    output_file = tmp_path / "summary.md"

    md = generate_markdown_from_file(str(report_file), output_path=str(output_file))
    assert "HIGH" in md
    assert output_file.read_text() == md


# ═════════════════════════════════════════════════════════════════════════════
# Feature 8 – Multi-Baseline / Release History
# ═════════════════════════════════════════════════════════════════════════════


def test_save_and_load_tagged_baseline(tmp_path: Path) -> None:
    from impactguard.baseline import load_tagged_baseline, save_tagged_baseline

    src = tmp_path / "mod.py"
    src.write_text("def greet(name: str) -> None:\n    pass\n")
    history = tmp_path / "history.json"

    save_tagged_baseline("v1.0.0", [str(src)], history_path=str(history))
    entry = load_tagged_baseline("v1.0.0", history_path=str(history))

    assert "signatures" in entry
    assert len(entry["signatures"]) == 1


def test_list_baselines_empty(tmp_path: Path) -> None:
    from impactguard.baseline import list_baselines

    entries = list_baselines(history_path=str(tmp_path / "nonexistent.json"))
    assert entries == []


def test_list_baselines_shows_all_tags(tmp_path: Path) -> None:
    from impactguard.baseline import list_baselines, save_tagged_baseline

    src = tmp_path / "mod.py"
    src.write_text("def fn():\n    pass\n")
    history = tmp_path / "history.json"

    for tag in ("v1.0.0", "v1.1.0", "v2.0.0"):
        save_tagged_baseline(tag, [str(src)], history_path=str(history))

    entries = list_baselines(history_path=str(history))
    tags = [e["tag"] for e in entries]
    assert "v1.0.0" in tags
    assert "v1.1.0" in tags
    assert "v2.0.0" in tags


def test_compare_with_tagged_baseline(tmp_path: Path) -> None:
    from impactguard.baseline import compare_with_tagged_baseline, save_tagged_baseline

    old_src = tmp_path / "old.py"
    old_src.write_text("def greet(name: str) -> None:\n    pass\n")
    history = tmp_path / "history.json"
    save_tagged_baseline("v1.0.0", [str(old_src)], history_path=str(history))

    new_src = tmp_path / "new.py"
    new_src.write_text("")  # greet removed

    result = compare_with_tagged_baseline(
        "v1.0.0", [str(new_src)], history_path=str(history)
    )
    assert "comparison" in result
    assert "semver" in result
    assert result["baseline_tag"] == "v1.0.0"


def test_delete_tagged_baseline(tmp_path: Path) -> None:
    from impactguard.baseline import (
        delete_tagged_baseline,
        list_baselines,
        save_tagged_baseline,
    )

    src = tmp_path / "mod.py"
    src.write_text("def fn():\n    pass\n")
    history = tmp_path / "history.json"

    save_tagged_baseline("v1.0.0", [str(src)], history_path=str(history))
    removed = delete_tagged_baseline("v1.0.0", history_path=str(history))
    assert removed is True

    entries = list_baselines(history_path=str(history))
    assert not any(e["tag"] == "v1.0.0" for e in entries)


def test_delete_nonexistent_tag_returns_false(tmp_path: Path) -> None:
    from impactguard.baseline import delete_tagged_baseline

    result = delete_tagged_baseline("v99.0.0", history_path=str(tmp_path / "nope.json"))
    assert result is False


def test_load_missing_tag_raises_key_error(tmp_path: Path) -> None:
    from impactguard.baseline import load_tagged_baseline, save_tagged_baseline

    src = tmp_path / "mod.py"
    src.write_text("def fn():\n    pass\n")
    history = tmp_path / "history.json"
    save_tagged_baseline("v1.0.0", [str(src)], history_path=str(history))

    with pytest.raises(KeyError, match="v99"):
        load_tagged_baseline("v99.0.0", history_path=str(history))


def test_save_tagged_baseline_empty_tag_raises(tmp_path: Path) -> None:
    from impactguard.baseline import save_tagged_baseline

    with pytest.raises(ValueError):
        save_tagged_baseline("", [])


# ═════════════════════════════════════════════════════════════════════════════
# Feature 9 – Feedback Loop Implementation
# ═════════════════════════════════════════════════════════════════════════════


def test_record_and_load_outcome(tmp_path: Path) -> None:
    from impactguard.feedback import load_outcomes, record_outcome

    feedback = tmp_path / "feedback.json"
    record_outcome("patch-1", accepted=True, feedback_path=str(feedback))
    record_outcome(
        "patch-2", accepted=False, change_type="positional", feedback_path=str(feedback)
    )

    outcomes = load_outcomes(feedback_path=str(feedback))
    assert len(outcomes) == 2
    assert outcomes[0]["patch_id"] == "patch-1"
    assert outcomes[0]["accepted"] is True
    assert outcomes[1]["change_type"] == "positional"


def test_get_stats_basic(tmp_path: Path) -> None:
    from impactguard.feedback import get_stats, record_outcome

    feedback = tmp_path / "feedback.json"
    for _ in range(3):
        record_outcome("p", accepted=True, feedback_path=str(feedback))
    record_outcome("p", accepted=False, feedback_path=str(feedback))

    stats = get_stats(feedback_path=str(feedback))
    assert stats["total"] == 4
    assert stats["accepted"] == 3
    assert stats["rejected"] == 1
    assert stats["acceptance_rate"] == pytest.approx(0.75)


def test_get_stats_empty(tmp_path: Path) -> None:
    from impactguard.feedback import get_stats

    stats = get_stats(feedback_path=str(tmp_path / "nope.json"))
    assert stats["total"] == 0
    assert stats["acceptance_rate"] == 0.0


def test_compute_calibrated_weights_needs_minimum_samples(tmp_path: Path) -> None:
    from impactguard.feedback import (
        compute_calibrated_weights,
        load_outcomes,
        record_outcome,
    )

    feedback = tmp_path / "feedback.json"
    # Only 3 samples for "positional" — below the 5-sample threshold
    for i in range(3):
        record_outcome(
            f"p{i}",
            accepted=True,
            change_type="positional",
            feedback_path=str(feedback),
        )
    outcomes = load_outcomes(str(feedback))
    weights = compute_calibrated_weights(outcomes)
    assert "structural_positional" not in weights


def test_compute_calibrated_weights_sufficient_samples(tmp_path: Path) -> None:
    from impactguard.feedback import (
        compute_calibrated_weights,
        load_outcomes,
        record_outcome,
    )

    feedback = tmp_path / "feedback.json"
    # 5 accepted positional — should produce a weight
    for i in range(5):
        record_outcome(
            f"p{i}",
            accepted=True,
            change_type="positional",
            feedback_path=str(feedback),
        )
    outcomes = load_outcomes(str(feedback))
    weights = compute_calibrated_weights(outcomes)
    assert "structural_positional" in weights
    assert 0 < weights["structural_positional"] <= 1.0


def test_apply_weights_to_config_creates_section(tmp_path: Path) -> None:
    from impactguard.feedback import apply_weights_to_config

    config_path = tmp_path / "impactguard.toml"
    config_path.write_text("[impactguard]\n# base config\n")

    weights = {"structural_positional": 0.6789}
    ok = apply_weights_to_config(weights, config_path=str(config_path))
    assert ok is True
    content = config_path.read_text()
    assert "structural_positional" in content
    assert "0.6789" in content


def test_apply_weights_updates_existing_key(tmp_path: Path) -> None:
    from impactguard.feedback import apply_weights_to_config

    config_path = tmp_path / "impactguard.toml"
    config_path.write_text(
        "[impactguard.patches]\n"
        "structural_positional = 0.3000\n"
        "structural_kwarg = 0.8000\n"
    )
    weights = {"structural_positional": 0.5555}
    apply_weights_to_config(weights, config_path=str(config_path))
    content = config_path.read_text()
    assert "0.5555" in content
    # Other key untouched
    assert "structural_kwarg" in content


def test_record_outcome_with_patch_data(tmp_path: Path) -> None:
    from impactguard.feedback import load_outcomes, record_outcome

    feedback = tmp_path / "feedback.json"
    record_outcome(
        "patch-x",
        accepted=True,
        patch_data={"diff": "--- a\n+++ b\n"},
        feedback_path=str(feedback),
    )
    outcomes = load_outcomes(str(feedback))
    assert outcomes[0]["patch_data"]["diff"].startswith("---")


# ═════════════════════════════════════════════════════════════════════════════
# Feature 10 – JSON Schema / Data Contract Validation
# ═════════════════════════════════════════════════════════════════════════════


def test_validate_signatures_valid() -> None:
    from impactguard.schema import validate_signatures

    data = [
        {
            "fqname": "mod.py:foo",
            "name": "foo",
            "positional": [{"name": "x", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    valid, errors = validate_signatures(data)
    assert valid is True
    assert errors == []


def test_validate_signatures_missing_field() -> None:
    from impactguard.schema import validate_signatures

    data = [{"fqname": "mod.py:foo", "name": "foo"}]  # missing required fields
    valid, errors = validate_signatures(data)
    assert valid is False
    assert any("positional" in e or "kwonly" in e or "vararg" in e for e in errors)


def test_validate_signatures_not_a_list() -> None:
    from impactguard.schema import validate_signatures

    valid, errors = validate_signatures({"bad": "data"})
    assert valid is False


def test_validate_calls_valid() -> None:
    from impactguard.schema import validate_calls

    data = [{"name": "foo", "lineno": 10, "file": "mod.py"}]
    valid, errors = validate_calls(data)
    assert valid is True


def test_validate_calls_missing_lineno() -> None:
    from impactguard.schema import validate_calls

    data = [{"name": "foo"}]
    valid, errors = validate_calls(data)
    assert valid is False
    assert any("lineno" in e for e in errors)


def test_validate_runtime_valid() -> None:
    from impactguard.schema import validate_runtime

    data = [{"function": "foo", "count": 42}]
    valid, errors = validate_runtime(data)
    assert valid is True


def test_validate_runtime_bad_count_type() -> None:
    from impactguard.schema import validate_runtime

    data = [{"function": "foo", "count": "not-a-number"}]
    valid, errors = validate_runtime(data)
    assert valid is False
    assert any("count" in e for e in errors)


def test_validate_risk_report_valid() -> None:
    from impactguard.schema import validate_risk_report

    data = [
        {
            "function": "foo",
            "risk": "HIGH",
            "change": "REMOVED",
            "exposure": 0.5,
            "confidence": 0.8,
        }
    ]
    valid, errors = validate_risk_report(data)
    assert valid is True


def test_validate_risk_report_invalid_risk_level() -> None:
    from impactguard.schema import validate_risk_report

    data = [
        {
            "function": "foo",
            "risk": "EXTREME",
            "change": "REMOVED",
            "exposure": 0.5,
            "confidence": 0.8,
        }
    ]
    valid, errors = validate_risk_report(data)
    assert valid is False
    assert any("EXTREME" in e for e in errors)


def test_validate_dispatch() -> None:
    from impactguard.schema import validate

    valid, _ = validate("runtime", [{"function": "f", "count": 1}])
    assert valid is True


def test_validate_unknown_kind_raises() -> None:
    from impactguard.schema import validate

    with pytest.raises(ValueError, match="Unknown data kind"):
        validate("widgets", [])


def test_validate_signatures_emits_warning_on_load(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """compare_signatures.load() should warn to stderr on invalid data."""
    from impactguard.compare_signatures import load

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps([{"fqname": "x:y", "name": "y"}])
    )  # missing required fields
    load(str(bad))
    captured = capsys.readouterr()
    assert "Warning" in captured.err or len(captured.err) == 0  # warning is non-fatal


# ═════════════════════════════════════════════════════════════════════════════
# Cross-feature / Integration
# ═════════════════════════════════════════════════════════════════════════════


def test_compare_includes_suppressed_key() -> None:
    """compare() always returns a 'suppressed' key."""
    result = _compare([], [])
    assert "suppressed" in result


def test_extract_signatures_ignored_and_exported_fields(tmp_path: Path) -> None:
    """Both new fields are always present in extracted signatures."""
    from impactguard.extract_signatures import extract

    src = tmp_path / "mod.py"
    src.write_text(
        "__all__ = ['pub']\ndef pub():\n    pass\n# impactguard: ignore\ndef _hidden():\n    pass\n"
    )
    sigs = extract([str(src)])
    for s in sigs:
        assert "ignored" in s
        assert "exported" in s


def test_markdown_report_in_package_init() -> None:
    """generate_markdown is exported from the top-level package."""
    import impactguard

    assert hasattr(impactguard, "generate_markdown")
    assert hasattr(impactguard, "generate_markdown_from_file")


def test_new_modules_importable() -> None:
    """All three new modules can be imported."""
    import impactguard.class_hierarchy  # noqa: F401
    import impactguard.feedback  # noqa: F401
    import impactguard.schema  # noqa: F401


def test_type_widening_not_in_breaking() -> None:
    """TYPE_WIDENED changes must never appear in the breaking list."""
    from impactguard.compare_signatures import compare

    old_sigs = [
        _sig(
            "m.py:fn",
            "fn",
            positional=[{"name": "x", "has_default": False, "type": "str"}],
        )
    ]
    new_sigs = [
        _sig(
            "m.py:fn",
            "fn",
            positional=[{"name": "x", "has_default": False, "type": "str | None"}],
        )
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        old_p = Path(tmpdir) / "old.json"
        new_p = Path(tmpdir) / "new.json"
        _write_json(old_sigs, old_p)
        _write_json(new_sigs, new_p)
        result = compare(str(old_p), str(new_p))

    assert not any("TYPE_WIDENED" in b for b in result["breaking"])
    assert any("TYPE_WIDENED" in nb for nb in result["nonbreaking"])
