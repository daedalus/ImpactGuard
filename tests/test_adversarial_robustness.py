"""Regression tests for robustness issues found by fuzzing ImpactGuard.

Each test class corresponds to one failure mode that previously crashed the
tool, silently dropped a breaking change, or degraded badly on large input.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from impactguard.compare_signatures import compare, load
from impactguard.extract_signatures import extract as extract_python
from impactguard.languages.lib import shared
from impactguard.languages.lib.registry import get_extractor_by_language
from impactguard.pipeline import (
    _extract_diff_files,
    _extract_group,
    _parse_unified_diff,
    _unquote_git_path,
)
from impactguard.suggest_fixes import get_line


def _sig(fqname: str = "m.py:f", **overrides: Any) -> dict[str, Any]:
    sig: dict[str, Any] = {
        "fqname": fqname,
        "name": fqname.split(":")[-1],
        "file": "m.py",
        "lineno": 1,
        "positional": [{"name": "a", "has_default": False, "type": "int"}],
        "kwonly": [{"name": "k", "has_default": True, "type": None}],
        "vararg": False,
        "kwarg": False,
        "return_type": "int",
        "decorators": [],
        "ignored": False,
        "exported": None,
    }
    sig.update(overrides)
    return sig


# ── compare(): malformed signature data must never crash ────────────────────


_MALFORMED = {
    "fqname_list": {"fqname": ["x"]},
    "fqname_none": {"fqname": None},
    "fqname_float": {"fqname": float("nan")},
    "positional_none": {"positional": None},
    "positional_str": {"positional": "abc"},
    "positional_dict": {"positional": {"a": 1}},
    "kwonly_none": {"kwonly": None},
    "arg_is_str": {"positional": ["a"]},
    "arg_is_none": {"positional": [None]},
    "arg_missing_name": {"positional": [{"has_default": False}]},
    "decorators_none": {"decorators": None},
    "decorators_mixed": {"decorators": [1, None, "ok"]},
    "return_type_int": {"return_type": 5},
    "return_type_list": {"return_type": ["int"]},
    "arg_type_dict": {"positional": [{"name": "a", "has_default": False, "type": {}}]},
    "name_list": {"name": ["f"]},
    "has_default_str": {"positional": [{"name": "a", "has_default": "false"}]},
}


class TestCompareMalformedSignatures:
    @pytest.mark.parametrize("side", ["old", "new", "both"])
    @pytest.mark.parametrize("label", sorted(_MALFORMED))
    def test_malformed_entry_does_not_crash(self, label: str, side: str) -> None:
        old = [_sig()]
        new = [_sig()]
        for target in {"old": [old], "new": [new], "both": [old, new]}[side]:
            target[0].update(copy.deepcopy(_MALFORMED[label]))
        result = compare(old, new, include_private=True)
        assert set(result) == {"breaking", "nonbreaking", "suppressed"}

    def test_input_is_not_mutated(self) -> None:
        old = [_sig(decorators=None, return_type=5)]
        snapshot = copy.deepcopy(old)
        compare(old, [_sig()], include_private=True)
        assert old == snapshot

    def test_unusable_new_entry_is_reported_as_removed(self) -> None:
        """Dropping a garbled *new* entry errs on the side of reporting."""
        result = compare([_sig()], [_sig(positional="garbage")], include_private=True)
        assert "REMOVED: m.py:f" in result["breaking"]

    def test_non_string_types_are_ignored_not_compared(self) -> None:
        result = compare([_sig()], [_sig(return_type=["int"])], include_private=True)
        assert result["breaking"] == []

    def test_string_has_default_is_treated_as_required(self) -> None:
        new = _sig()
        new["positional"] = [
            {"name": "a", "has_default": False},
            {"name": "b", "has_default": "true"},
        ]
        result = compare([_sig()], [new], include_private=True)
        assert "REQUIRED_POSITIONAL_ADDED: m.py:f" in result["breaking"]

    def test_valid_change_still_detected_next_to_garbage(self) -> None:
        old = [_sig("m.py:f"), {"fqname": None}, 42]
        new_f = _sig("m.py:f")
        new_f["positional"].append({"name": "b", "has_default": False})
        new = [new_f, {"fqname": ["junk"]}]
        result = compare(old, new, include_private=True)
        assert result["breaking"] == ["REQUIRED_POSITIONAL_ADDED: m.py:f"]


class TestSignatureFileLoading:
    def test_deeply_nested_json_raises_value_error(self, tmp_path: Path) -> None:
        f = tmp_path / "deep.json"
        f.write_text("[" * 100_000 + "]" * 100_000)
        with pytest.raises(ValueError, match="nesting too deep"):
            load(str(f))

    def test_non_utf8_file_raises_value_error(self, tmp_path: Path) -> None:
        f = tmp_path / "latin1.json"
        f.write_bytes(b'[{"fqname": "caf\xe9"}]')
        with pytest.raises(ValueError, match="UTF-8"):
            load(str(f))

    def test_utf8_bom_is_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "bom.json"
        f.write_bytes(b"\xef\xbb\xbf" + json.dumps([_sig()]).encode())
        assert list(load(str(f))) == ["m.py:f"]

    def test_nan_fqname_is_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "nan.json"
        f.write_text('[{"fqname": NaN, "positional": [], "kwonly": []}]')
        assert load(str(f)) == {}


# ── Unified diff parsing ────────────────────────────────────────────────────


def _diff(old_path: str, new_path: str, old: str, new: str) -> str:
    return f"--- {old_path}\n+++ {new_path}\n@@ -1 +1 @@\n-{old}\n+{new}\n"


class TestUnifiedDiffParsing:
    @pytest.mark.parametrize(
        ("quoted", "expected"),
        [
            ('"a/caf\\303\\251.py"', "a/café.py"),
            ('"a/my mod.py"', "a/my mod.py"),
            ('"a/q\\"uote\\\\d.py"', 'a/q"uote\\d.py'),
            ('"a/tab\\there.py"', "a/tab\there.py"),
            ("a/plain.py", "a/plain.py"),
            ('"', '"'),
        ],
    )
    def test_unquote_git_path(self, quoted: str, expected: str) -> None:
        assert _unquote_git_path(quoted) == expected

    def test_git_quoted_non_ascii_path_is_not_dropped(self) -> None:
        text = _diff(
            '"a/caf\\303\\251.py"',
            '"b/caf\\303\\251.py"',
            "def f(a): pass",
            "def f(a, b): pass",
        )
        assert _parse_unified_diff(text) == {
            "café.py": ("def f(a): pass", "def f(a, b): pass")
        }

    def test_git_quoted_path_with_space_and_timestamp(self) -> None:
        text = _diff(
            '"a/my mod.py"\t2024-01-01 00:00:00',
            '"b/my mod.py"\t2024-01-02 00:00:00',
            "def f(a): pass",
            "def f(): pass",
        )
        assert list(_parse_unified_diff(text)) == ["my mod.py"]

    def test_quoted_traversal_still_rejected(self) -> None:
        text = _diff(
            '"a/../../etc/evil.py"',
            '"b/../../etc/evil.py"',
            "def f(a): pass",
            "def f(): pass",
        )
        assert _parse_unified_diff(text) == {}

    def test_repeated_file_sections_are_merged(self) -> None:
        text = _diff("a/x.py", "b/x.py", "def f(a): pass", "def f(a, b): pass")
        text += _diff("a/x.py", "b/x.py", "def g(a): pass", "def g(): pass")
        old, new = _parse_unified_diff(text)["x.py"]
        assert "def f(a): pass" in old and "def g(a): pass" in old
        assert "def f(a, b): pass" in new and "def g(): pass" in new

    def test_file_and_directory_collision_does_not_crash(self) -> None:
        text = _diff("a/a.py", "b/a.py", "def f(): pass", "def f(x): pass")
        text += _diff("a/a.py/b.py", "b/a.py/b.py", "def g(): pass", "def g(x): pass")
        old_files, new_files, _, _ = _extract_diff_files(_parse_unified_diff(text))
        assert len(old_files) == 1 and old_files[0].endswith("a.py")
        assert len(new_files) == 1

    def test_non_ascii_content_written_as_utf8(self) -> None:
        text = _diff("a/u.py", "b/u.py", "def f(): return 'ü'", "def f(x): return '€'")
        _, new_files, _, _ = _extract_diff_files(_parse_unified_diff(text))
        assert "€" in Path(new_files[0]).read_text(encoding="utf-8")


# ── Extraction fault isolation ──────────────────────────────────────────────


class _FlakyExtractor:
    language = "fake"

    def __init__(self, bad: str, exc: BaseException) -> None:
        self.bad = bad
        self.exc = exc

    def extract_signatures(
        self, files: list[str], _base_path: str | None = None
    ) -> list[dict[str, Any]]:
        if self.bad in files:
            raise self.exc
        return [_sig(f"{f}:fn") for f in files]


class TestExtractionFaultIsolation:
    @pytest.mark.parametrize(
        "exc",
        [RecursionError("too deep"), ValueError("bad"), UnicodeDecodeError("utf-8", b"", 0, 1, "x")],
    )
    def test_one_bad_file_does_not_drop_the_group(self, exc: BaseException) -> None:
        stats: dict[str, int] = {}
        events: list[dict[str, str]] = []
        result = _extract_group(
            _FlakyExtractor("bad.x", exc), ["a.x", "bad.x", "b.x"], None, False, stats, events
        )
        assert sorted(r["fqname"] for r in result) == ["a.x:fn", "b.x:fn"]
        assert stats["parse_failures"] == 1
        assert len(events) == 1 and events[0]["file"] == "bad.x"

    def test_single_file_failure_recorded(self) -> None:
        stats: dict[str, int] = {}
        result = _extract_group(
            _FlakyExtractor("bad.x", RecursionError()), ["bad.x"], None, False, stats, None
        )
        assert result == []
        assert stats["parse_failures"] == 1


# ── Deeply nested / long-chain sources ──────────────────────────────────────


_CHAIN_TEMPLATES = {
    "javascript": ("export function f(a) {{ const s = {expr}; g(a); }}\n", ".js"),
    "typescript": ("export function f(a: number) {{ const s = {expr}; g(a); }}\n", ".ts"),
    "csharp": ("class A {{ public void F(int a) {{ var s = {expr}; G(a); }} }}\n", ".cs"),
    "kotlin": ("fun f(a: Int) {{ val s = {expr}\n g(a) }}\n", ".kt"),
    "swift": ("func f(a: Int) {{ let s = {expr}\n g(a) }}\n", ".swift"),
    "zig": ("pub fn f(a: i32) void {{ const s = {expr}; g(a); }}\n", ".zig"),
    "java": ("class A {{ public void f(int a) {{ int s = {expr}; g(a); }} }}\n", ".java"),
    "rust": ("pub fn f(a: i32) {{ let s = {expr}; g(a); }}\n", ".rs"),
    "go": ("package p\nfunc F(a int) {{ s := {expr}; g(a) }}\n", ".go"),
}


class TestDeepTrees:
    @pytest.mark.parametrize("lang", sorted(_CHAIN_TEMPLATES))
    def test_long_expression_chain(self, lang: str, tmp_path: Path) -> None:
        """A 3000-term ``1 + 1 + ...`` (e.g. generated tables) must not overflow."""
        template, ext = _CHAIN_TEMPLATES[lang]
        src = tmp_path / f"chain{ext}"
        src.write_text(template.format(expr=" + ".join(["1"] * 3000)))
        extractor = get_extractor_by_language(lang)
        assert extractor is not None
        sigs = extractor.extract_signatures([str(src)])
        assert len(sigs) == 1
        calls = extractor.extract_calls(src)
        assert any(c["name"].lower().endswith("g") for c in calls)

    @pytest.mark.parametrize("lang", sorted(_CHAIN_TEMPLATES))
    def test_deeply_nested_calls_extracted(self, lang: str, tmp_path: Path) -> None:
        _, ext = _CHAIN_TEMPLATES[lang]
        src = tmp_path / f"deep{ext}"
        src.write_text("x = " + "(" * 20_000 + "1" + ")" * 20_000 + "\n")
        extractor = get_extractor_by_language(lang)
        assert extractor is not None
        assert isinstance(extractor.extract_calls(src), list)

    def test_iter_preorder_matches_recursive_order(self) -> None:
        class N:
            def __init__(self, name: str, *children: N) -> None:
                self.name = name
                self.children = list(children)

        tree = N("r", N("a", N("a1"), N("a2", N("a2x"))), N("b"), N("c", N("c1")))

        def rec(n: N) -> list[str]:
            return [n.name] + [x for c in n.children for x in rec(c)]

        assert [n.name for n in shared.iter_preorder(tree)] == rec(tree)


# ── Ignore-comment line alignment ───────────────────────────────────────────


class TestIgnoreCommentLineAlignment:
    """Form feeds (``^L`` page breaks) must not shift line numbering."""

    def test_c_form_feed(self, tmp_path: Path) -> None:
        src = tmp_path / "ff.c"
        src.write_text(
            "int a(int x) { return x; }\n\f\n// impactguard: ignore\n"
            "int b(int x) { return x; }\nint c(int x) { return x; }\n"
        )
        c_ex = get_extractor_by_language("c")
        assert c_ex is not None
        ignored = {s["name"]: s["ignored"] for s in c_ex.extract_signatures([str(src)])}
        assert ignored == {"a": False, "b": True, "c": False}

    @pytest.mark.parametrize("sep", ["\f", "\v", "\x1c", " ", "\x85"])
    def test_python_exotic_separators(self, tmp_path: Path, sep: str) -> None:
        src = tmp_path / "ff.py"
        src.write_text(
            # Inside a comment the separator is legal Python, but
            # ``str.splitlines()`` would still treat it as a line break.
            f"def a(x): pass\n# page{sep}break\n# impactguard: ignore\n"
            "def b(x): pass\ndef c(x): pass\n",
            encoding="utf-8",
        )
        ignored = {s["name"]: s["ignored"] for s in extract_python([str(src)])}
        assert ignored == {"a": False, "b": True, "c": False}

    def test_crlf_still_aligned(self, tmp_path: Path) -> None:
        src = tmp_path / "crlf.py"
        src.write_bytes(
            b"def a(x): pass\r\n# impactguard: ignore\r\ndef b(x): pass\r\ndef c(x): pass\r\n"
        )
        ignored = {s["name"]: s["ignored"] for s in extract_python([str(src)])}
        assert ignored == {"a": False, "b": True, "c": False}

    def test_source_lines_cached(self) -> None:
        source = b"\n".join(b"line %d" % i for i in range(1000))
        shared._source_lines.cache_clear()
        for i in range(500):
            shared.has_ignore_comment(source, i)
        info = shared._source_lines.cache_info()
        assert info.misses == 1 and info.hits == 499


class TestGetLine:
    def test_non_utf8_file_does_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        Path("l1.py").write_bytes(b"x = 1\ndef caf\xe9(): pass\n")
        assert get_line("l1.py", 2).startswith("def caf")

    def test_form_feed_alignment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        Path("ff.py").write_text("a = 1\n\f\nb = 2\n")
        assert get_line("ff.py", 3) == "b = 2"
