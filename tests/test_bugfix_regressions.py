"""Regression tests for bugs fixed in the correctness audit."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import threading
from pathlib import Path
from unittest import mock

import pytest

# ── Z3 type model ─────────────────────────────────────────────────────────────

class TestTypeSubsumption:
    @pytest.fixture(autouse=True)
    def _need_z3(self) -> None:
        pytest.importorskip("z3")

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("str", "MyClass"),
            ("list[int]", "int"),
            ("tuple[int, str]", "int"),
            ("int", "Callable[[int], str]"),
        ],
    )
    def test_unrelated_types_are_not_widening(self, old: str, new: str) -> None:
        from impactguard.constraint_check import check_subsumption

        assert check_subsumption(old, new) == "changed"

    def test_equivalent_spellings_are_no_change(self) -> None:
        from impactguard.constraint_check import check_subsumption

        assert check_subsumption("Optional[int]", "int | None") is None
        assert check_subsumption("int | str", "str | int") is None

    def test_nested_generic_union_split_is_bracket_aware(self) -> None:
        from impactguard.constraint_check import check_subsumption

        assert check_subsumption("Union[dict[str, int], None]", "dict[str, int]") == "narrowing"
        assert check_subsumption("dict[str,int]", "dict[str, int] | None") == "widening"

    def test_any_still_top(self) -> None:
        from impactguard.constraint_check import check_subsumption

        assert check_subsumption("MyClass", "Any") == "widening"


# ── compare_signatures ────────────────────────────────────────────────────────


def _sig(name: str, positional: list[dict], **extra: object) -> dict:
    base = {
        "fqname": f"m.py:{name}",
        "name": name,
        "positional": positional,
        "kwonly": [],
        "vararg": False,
        "kwarg": False,
        "decorators": [],
        "return_type": None,
    }
    base.update(extra)
    return base


def test_ignore_comment_added_in_new_version_suppresses_change() -> None:
    from impactguard.compare_signatures import compare

    old = [_sig("f", [{"name": "a", "has_default": False}])]
    new = [
        _sig(
            "f",
            [{"name": "a", "has_default": False}, {"name": "b", "has_default": False}],
            ignored=True,
        )
    ]
    result = compare(old, new, include_private=True)
    assert result["breaking"] == []
    assert result["suppressed"] == ["m.py:f"]


def test_reordered_union_is_not_a_type_change() -> None:
    from impactguard.compare_signatures import compare

    old = [_sig("f", [{"name": "a", "has_default": False, "type": "int | str"}])]
    new = [_sig("f", [{"name": "a", "has_default": False, "type": "str | int"}])]
    result = compare(old, new, include_private=True)
    assert result["breaking"] == []
    assert result["nonbreaking"] == []


# ── risk_gate ─────────────────────────────────────────────────────────────────


def test_risk_gate_keeps_worst_change_per_function(tmp_path: Path) -> None:
    from impactguard.risk_gate import run_from_changes

    runtime = tmp_path / "rt.json"
    runtime.write_text("[]")
    report = run_from_changes(
        [
            "DECORATOR_REMOVED: m.py:f @cache",
            "REQUIRED_POSITIONAL_ADDED: m.py:f",
        ],
        str(runtime),
    )
    assert len(report) == 1
    assert report[0]["risk"] == "HIGH"
    assert report[0]["change"] == "REQUIRED_POSITIONAL_ADDED"


# ── impact_analysis ───────────────────────────────────────────────────────────


def _write(path: Path, data: object) -> str:
    path.write_text(json.dumps(data))
    return str(path)


def _foo_sig() -> dict:
    return {
        "fqname": "pkg/lib.py:foo",
        "name": "foo",
        "positional": [
            {"name": "a", "has_default": False},
            {"name": "b", "has_default": False},
        ],
        "kwonly": [],
        "vararg": False,
        "kwarg": False,
    }


@pytest.mark.parametrize(
    "call",
    [
        {"fqname": "pkg.lib.foo", "args": 1},  # analyze_module style
        {"fqname": "lib.foo", "args": 1},
        {"name": "foo", "args": 1},  # extract_calls style
    ],
)
def test_module_level_call_resolves_to_signature(tmp_path: Path, call: dict) -> None:
    from impactguard.impact_analysis import analyze

    sigs = _write(tmp_path / "s.json", [_foo_sig()])
    calls = _write(tmp_path / "c.json", [{**call, "file": "main.py", "lineno": 3}])
    issues = analyze(sigs, calls)
    assert [i["function"] for i in issues] == ["pkg/lib.py:foo"]
    assert issues[0]["change"] == "missing args"
    assert issues[0]["risk"] == "HIGH"


def test_keyword_argument_satisfies_positional_param(tmp_path: Path) -> None:
    from impactguard.impact_analysis import analyze

    sigs = _write(tmp_path / "s.json", [_foo_sig()])
    calls = _write(
        tmp_path / "c.json",
        [{"fqname": "pkg.lib.foo", "args": 1, "kwargs": ["b"], "file": "x.py"}],
    )
    assert analyze(sigs, calls) == []


def test_python_starargs_flag_spelling_is_honoured(tmp_path: Path) -> None:
    from impactguard.impact_analysis import analyze

    sigs = _write(tmp_path / "s.json", [_foo_sig()])
    calls = _write(
        tmp_path / "c.json",
        [
            {"fqname": "pkg.lib.foo", "args": 1, "starargs": True, "file": "x.py"},
            {"fqname": "pkg.lib.foo", "args": 0, "kwargs_any": True, "file": "x.py"},
        ],
    )
    assert analyze(sigs, calls) == []


def test_detect_uncalled_resolves_dotted_call_names() -> None:
    from impactguard.impact_analysis import detect_uncalled_changes

    funcs = {"pkg/lib.py:foo": _foo_sig()}
    issues = detect_uncalled_changes(
        ["REQUIRED_POSITIONAL_ADDED: pkg/lib.py:foo"],
        funcs,
        [{"fqname": "pkg.lib.foo", "args": 1}],
    )
    assert issues == []


def test_transitive_callers_found_via_resolved_names() -> None:
    from impactguard.impact_analysis import build_call_graph, find_transitive_callers

    funcs = {"pkg/lib.py:foo": _foo_sig()}
    graph = build_call_graph([{"fqname": "pkg.lib.foo", "caller": "run"}], funcs)
    assert find_transitive_callers({"pkg/lib.py:foo"}, graph) == {"run": 1}


def test_fqname_to_runtime_key_only_strips_py_suffix() -> None:
    from impactguard.impact_analysis import _fqname_to_runtime_key

    assert _fqname_to_runtime_key("my.pyramid/app.py:f") == "my.pyramid.app.f"


# ── analyze_module ────────────────────────────────────────────────────────────


def test_calls_inside_assignments_are_recorded() -> None:
    from impactguard.analyze_module import Analyzer

    a = Analyzer("m.py")
    a.visit(ast.parse("x = foo(1)\ny: int = bar(2)\nbaz(3)\n"))
    assert sorted(c["fqname"] for c in a.calls) == ["bar", "baz", "foo"]


# ── unified diff parsing ──────────────────────────────────────────────────────


def test_diff_removed_line_starting_with_dashes_is_not_a_header() -> None:
    from impactguard.pipeline import _parse_unified_diff

    diff = (
        "--- a/m.hs\n"
        "+++ b/m.hs\n"
        "@@ -1,2 +1,2 @@\n"
        "--- impactguard: ignore\n"
        "+-- note\n"
        " foo x = x\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1 +1 @@\n"
        "-def f(a):\n"
        "+def f(a, b):\n"
    )
    files = _parse_unified_diff(diff)
    assert files["m.hs"] == ("-- impactguard: ignore\nfoo x = x", "-- note\nfoo x = x")
    assert files["a.py"] == ("def f(a):", "def f(a, b):")


# ── cache ─────────────────────────────────────────────────────────────────────


def test_cache_l1_is_per_instance(tmp_path: Path) -> None:
    from impactguard.cache import Cache

    c1 = Cache(db_path=str(tmp_path / "a.db"))
    c2 = Cache(db_path=str(tmp_path / "b.db"))
    try:
        c1.set("k", "one")
        assert c2.get("k") is None
    finally:
        c1.close()
        c2.close()


def test_cache_ttl_respected_in_memory(tmp_path: Path) -> None:
    from impactguard.cache import Cache

    c = Cache(db_path=str(tmp_path / "a.db"))
    try:
        with mock.patch("impactguard.cache.time.time", return_value=1000.0):
            c.set("k", "v", ttl_seconds=10)
        with mock.patch("impactguard.cache.time.time", return_value=2000.0):
            assert c.get("k") is None
    finally:
        c.close()


def test_cached_ast_keeps_line_numbers_across_cache_hit(tmp_path: Path) -> None:
    from impactguard.cache import Cache, _unwrap_value, _wrap_value

    source = "# header\n\n\ndef f():\n    return 1\n"
    tree = ast.parse(source)
    restored = _unwrap_value(_wrap_value(tree))
    assert restored.body[0].lineno == 4
    c = Cache(db_path=str(tmp_path / "a.db"))
    try:
        c.set("ast3:x", tree)
        c._mem.clear()
        assert c.get("ast3:x").body[0].lineno == 4
    finally:
        c.close()


# ── call graph ────────────────────────────────────────────────────────────────


def test_call_graph_closed_for_all_threads(tmp_path: Path) -> None:
    from impactguard.call_graph import CallGraphDB

    db = CallGraphDB(tmp_path)
    errors: list[str] = []
    ready = threading.Event()
    go = threading.Event()

    def worker() -> None:
        db.con  # create this thread's connection
        ready.set()
        go.wait()
        try:
            db.con.execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)

    t = threading.Thread(target=worker)
    t.start()
    ready.wait()
    db.close()
    go.set()
    t.join()
    assert errors == ["RuntimeError"]


def test_call_graph_resolves_nested_dotted_import(tmp_path: Path) -> None:
    from impactguard.call_graph import CallGraphDB

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "my_mod.py").write_text("def helper(a):\n    return a\n")
    # Decoy that a ``_`` LIKE wildcard would wrongly match.
    (tmp_path / "pkg" / "myXmod.py").write_text("def helper(a):\n    return a\n")
    db = CallGraphDB(tmp_path)
    try:
        db.build([str(p) for p in sorted((tmp_path / "pkg").glob("*.py"))])
        assert db._resolve_from_dotted("pkg.my_mod.helper") == "pkg/my_mod.py:helper"
    finally:
        db.close()


# ── shared helpers / hooks ────────────────────────────────────────────────────


def test_shared_imports_without_tree_sitter() -> None:
    import sys

    code = (
        "import sys, builtins\n"
        "real = builtins.__import__\n"
        "def fake(name, *a, **k):\n"
        "    if name == 'tree_sitter' or name.startswith('tree_sitter.'):\n"
        "        raise ImportError(name)\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = fake\n"
        "import impactguard.languages.lib.shared as s\n"
        "assert s._TREE_SITTER_AVAILABLE is False\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_post_commit_hook_restores_env_on_early_return() -> None:
    from impactguard.__main__ import post_commit_hook

    os.environ.pop("SKIP_SIGNATURE_HOOK", None)
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with mock.patch("subprocess.run", return_value=fake):
        assert post_commit_hook() == 0
    assert "SKIP_SIGNATURE_HOOK" not in os.environ


def test_feedback_ignores_malformed_entries(tmp_path: Path) -> None:
    from impactguard.feedback import get_stats

    path = tmp_path / "fb.json"
    path.write_text(json.dumps([1, "x", {"accepted": True, "change_type": "kwarg"}]))
    stats = get_stats(str(path))
    assert stats["total"] == 1


def test_enforce_report_rejects_non_list(tmp_path: Path) -> None:
    from impactguard.enforce_gate import enforce_report

    path = tmp_path / "r.json"
    path.write_text(json.dumps({"risk": "HIGH"}))
    assert enforce_report(str(path), block_unknown=False) == 2

