"""Tests for ImpactGuard's structural decay model (decay_model.py)."""

import sys
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from impactguard.decay_model import (
    Unit,
    compute_file_impact,
    parse_unified_diff,
    diff_line_count,
    extract_units,
    score_change,
    enforce,
    is_warning,
    render_text,
    render_json,
    DEFAULT_MAX_DIFF_LINES,
)


# ── extract_units / cyclomatic complexity ──────────────────────────────────


def test_extract_units_free_function():
    src = "def f(x):\n    return x\n"
    units = extract_units(src, "m.py")
    assert len(units) == 1
    assert units[0].name == "f"
    assert units[0].container == "<module>"
    assert units[0].cc == 1


def test_extract_units_branching_raises_cc():
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    elif x == 2:\n"
        "        return 2\n"
        "    else:\n"
        "        return 3\n"
    )
    units = extract_units(src, "m.py")
    assert units[0].cc >= 3  # base 1 + if + elif(=another if)


def test_extract_units_method_container_is_class_name():
    src = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        pass\n"
        "    def baz(self):\n"
        "        pass\n"
    )
    units = extract_units(src, "m.py")
    names = {u.name for u in units}
    assert names == {"Foo.bar", "Foo.baz"}
    assert all(u.container == "Foo" for u in units)


def test_generic_fallback_for_non_python():
    src = "function f() { return 1; }\n"
    units = extract_units(src, "m.js")
    assert len(units) == 1
    assert units[0].container == "<file>"
    assert units[0].cc == 1


# ── parse_unified_diff ──────────────────────────────────────────────────────


def test_parse_unified_diff_basic():
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -10,2 +10,3 @@\n"
        " context\n"
        "-old line\n"
        "+new line\n"
        "+another new line\n"
    )
    files = parse_unified_diff(diff)
    assert "foo.py" in files
    added, removed = files["foo.py"]
    assert added == [(10, 3)]
    assert removed == [(10, 2)]
    assert diff_line_count(added, removed) == 5


def test_parse_unified_diff_new_file_has_no_removed_range():
    diff = (
        "diff --git a/new.py b/new.py\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,4 @@\n"
        "+a\n+b\n+c\n+d\n"
    )
    files = parse_unified_diff(diff)
    added, removed = files["new.py"]
    assert removed == []
    assert added == [(1, 4)]


# ── compute_file_impact: the core WMC_other behaviour ──────────────────────


def _unit(name, container, cc, start, end):
    return Unit(name=name, container=container, cc=cc, start_line=start, end_line=end)


def test_new_method_on_heavy_class_is_expensive():
    """Adding a method to a class that already has a lot of complexity
    should cost more than adding the same method to a brand-new class."""
    before_heavy = [
        _unit("Heavy.a", "Heavy", 5, 1, 3),
        _unit("Heavy.b", "Heavy", 7, 4, 6),
    ]
    after_heavy = before_heavy + [_unit("Heavy.c", "Heavy", 2, 7, 9)]
    added = [(7, 3)]
    removed = []
    src_before = ["" for _ in range(6)]
    src_after = ["" for _ in range(9)]

    fi_heavy = compute_file_impact(
        "heavy.py", before_heavy, after_heavy, src_before, src_after, added, removed
    )

    before_fresh = []
    after_fresh = [_unit("Fresh.c", "Fresh", 2, 7, 9)]
    fi_fresh = compute_file_impact(
        "fresh.py", before_fresh, after_fresh, src_before, src_after, added, removed
    )

    assert fi_heavy.godclass_cost > fi_fresh.godclass_cost
    assert fi_fresh.godclass_cost == 1 * 2 * 3  # wmc floored to 1


def test_mutation_of_existing_unit_is_scored_as_mutation():
    before = [_unit("Foo.bar", "Foo", 3, 1, 5), _unit("Foo.baz", "Foo", 4, 6, 10)]
    after = [_unit("Foo.bar", "Foo", 3, 1, 6), _unit("Foo.baz", "Foo", 4, 7, 11)]
    added = [(1, 6)]
    removed = [(1, 5)]
    src = ["" for _ in range(11)]

    fi = compute_file_impact("foo.py", before, after, src, src, added, removed)
    kinds = {u.name: u.kind for u in fi.units}
    assert kinds["Foo.bar"] == "mutation"
    assert fi.mut_units == 1
    assert fi.new_units == 0


def test_untouched_units_are_not_scored():
    before = [_unit("Foo.bar", "Foo", 3, 1, 5), _unit("Foo.baz", "Foo", 4, 6, 10)]
    after = before
    added = [(1, 1)]  # touches only bar's range
    removed = []
    src = ["" for _ in range(10)]

    fi = compute_file_impact("foo.py", before, after, src, src, added, removed)
    names = {u.name for u in fi.units}
    assert "Foo.baz" not in names


# ── score_change / enforce integration (real temp git repo) ────────────────


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_score_change_staged_new_file():
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, "init", "-q")
        _git(tmp, "config", "user.email", "t@example.com")
        _git(tmp, "config", "user.name", "T")
        (Path(tmp) / "a.py").write_text("def f():\n    return 1\n")
        _git(tmp, "add", "a.py")
        _git(tmp, "commit", "-q", "-m", "init")

        (Path(tmp) / "a.py").write_text(
            "def f():\n    return 1\n\n\ndef g():\n    return 2\n"
        )
        _git(tmp, "add", "a.py")

        score = score_change(repo_path=tmp, mode="staged")
        assert score.files_changed == 1
        assert score.impact > 0
        fi = score.file_impacts[0]
        assert fi.new_units == 1  # g() is a new unit


def test_skip_oversized_diff():
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, "init", "-q")
        _git(tmp, "config", "user.email", "t@example.com")
        _git(tmp, "config", "user.name", "T")
        (Path(tmp) / "a.py").write_text("x = 1\n")
        _git(tmp, "add", "a.py")
        _git(tmp, "commit", "-q", "-m", "init")

        huge = "\n".join(f"x{i} = {i}" for i in range(50))
        (Path(tmp) / "a.py").write_text(huge)
        _git(tmp, "add", "a.py")

        score = score_change(repo_path=tmp, mode="staged", max_diff_lines=5)
        assert score.files_changed == 0
        assert len(score.skipped) == 1
        assert score.skipped[0].path == "a.py"


def test_enforce_modes():
    from impactguard.decay_model import DecayScore

    score = DecayScore(impact=1000)
    assert enforce(score, warn_at=100, block_at=2000, enforcement="block") == (False, 0)
    assert enforce(score, warn_at=100, block_at=500, enforcement="block") == (True, 2)
    assert enforce(score, warn_at=100, block_at=500, enforcement="warn") == (False, 0)
    assert enforce(score, warn_at=100, block_at=500, enforcement="off") == (False, 0)
    assert is_warning(score, warn_at=100) is True
    assert is_warning(score, warn_at=10_000) is False


def test_render_text_and_json_rank_by_cost():
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, "init", "-q")
        _git(tmp, "config", "user.email", "t@example.com")
        _git(tmp, "config", "user.name", "T")
        (Path(tmp) / "a.py").write_text("def f():\n    return 1\n")
        _git(tmp, "add", "a.py")
        _git(tmp, "commit", "-q", "-m", "init")

        (Path(tmp) / "a.py").write_text(
            "def f():\n    return 1\n\n\ndef g():\n    return 2\n"
        )
        _git(tmp, "add", "a.py")

        score = score_change(repo_path=tmp, mode="staged")
        text = render_text(score)
        assert "structural decay impact" in text
        assert "a.py" in text

        data = render_json(score)
        assert data["impact"] == score.impact
        assert data["files"][0]["path"] == "a.py"
