"""Tests for the ImpactGuard multi-language support layer.

Covers:
* LanguageExtractor protocol
* Language registry (register / lookup / detect)
* Python extractor (delegates to existing code)
* TypeScript extractor (tree-sitter and regex paths)
* Pluggable type-compat in compare_signatures.compare()
* CLI --language flag for extract / extract-calls
* Config defaults for [impactguard.languages]
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ── Language registry ─────────────────────────────────────────────────────────


class TestRegistry:
    def test_get_extractor_python(self) -> None:
        from impactguard.languages.registry import get_extractor
        ext = get_extractor("mymodule.py")
        assert ext is not None
        assert ext.language == "python"

    def test_get_extractor_typescript(self) -> None:
        from impactguard.languages.registry import get_extractor
        ext = get_extractor("api.ts")
        assert ext is not None
        assert ext.language == "typescript"

    def test_get_extractor_tsx(self) -> None:
        from impactguard.languages.registry import get_extractor
        ext = get_extractor("Component.tsx")
        assert ext is not None
        assert ext.language == "typescript"

    def test_get_extractor_unknown(self) -> None:
        from impactguard.languages.registry import get_extractor
        assert get_extractor("file.go") is None

    def test_get_extractor_by_language_python(self) -> None:
        from impactguard.languages.registry import get_extractor_by_language
        ext = get_extractor_by_language("python")
        assert ext is not None
        assert ext.language == "python"

    def test_get_extractor_by_language_typescript(self) -> None:
        from impactguard.languages.registry import get_extractor_by_language
        ext = get_extractor_by_language("typescript")
        assert ext is not None

    def test_get_extractor_by_language_unknown(self) -> None:
        from impactguard.languages.registry import get_extractor_by_language
        assert get_extractor_by_language("cobol") is None

    def test_detect_language_python(self) -> None:
        from impactguard.languages.registry import detect_language
        assert detect_language("foo.py") == "python"

    def test_detect_language_typescript(self) -> None:
        from impactguard.languages.registry import detect_language
        assert detect_language("foo.ts") == "typescript"
        assert detect_language("foo.tsx") == "typescript"

    def test_detect_language_unknown(self) -> None:
        from impactguard.languages.registry import detect_language
        assert detect_language("foo.rb") is None

    def test_list_languages(self) -> None:
        from impactguard.languages.registry import list_languages
        langs = list_languages()
        assert "python" in langs
        assert "typescript" in langs

    def test_list_extensions(self) -> None:
        from impactguard.languages.registry import list_extensions
        exts = list_extensions()
        assert ".py" in exts
        assert ".ts" in exts
        assert ".tsx" in exts

    def test_register_custom_language(self) -> None:
        from impactguard.languages.registry import register, get_extractor_by_language

        class FakeLang:
            language = "fake"
            extensions = [".fake"]

            def extract_signatures(self, files, base_path=None):
                return []

            def extract_calls(self, path):
                return []

            def parse_union_members(self, type_str):
                return frozenset({type_str})

        register(FakeLang())
        ext = get_extractor_by_language("fake")
        assert ext is not None
        assert ext.language == "fake"

    def test_case_insensitive_lookup(self) -> None:
        from impactguard.languages.registry import get_extractor_by_language
        assert get_extractor_by_language("PYTHON") is not None
        assert get_extractor_by_language("TypeScript") is not None


# ── LanguageExtractor protocol checks ─────────────────────────────────────────


class TestLanguageExtractorProtocol:
    def test_python_satisfies_protocol(self) -> None:
        from impactguard.languages.base import LanguageExtractor
        from impactguard.languages.python import PythonExtractor
        assert isinstance(PythonExtractor(), LanguageExtractor)

    def test_typescript_satisfies_protocol(self) -> None:
        from impactguard.languages.base import LanguageExtractor
        from impactguard.languages.typescript import TypeScriptExtractor
        assert isinstance(TypeScriptExtractor(), LanguageExtractor)


# ── Python extractor ──────────────────────────────────────────────────────────


class TestPythonExtractor:
    def test_extract_signatures_basic(self, tmp_path: Path) -> None:
        f = _write(tmp_path, "mod.py", "def foo(x: int, y: str = 'hi') -> None: pass\n")
        from impactguard.languages.python import PythonExtractor
        sigs = PythonExtractor().extract_signatures([str(f)])
        assert len(sigs) == 1
        sig = sigs[0]
        assert sig["name"] == "foo"
        assert sig["fqname"] == "mod.py:foo"
        assert len(sig["positional"]) == 2
        assert sig["positional"][0]["name"] == "x"
        assert sig["positional"][0]["has_default"] is False
        assert sig["positional"][1]["has_default"] is True
        assert sig["return_type"] == "None"
        assert sig["is_async"] is False

    def test_extract_calls(self, tmp_path: Path) -> None:
        f = _write(tmp_path, "mod.py", "bar(1, 2)\n")
        from impactguard.languages.python import PythonExtractor
        calls = PythonExtractor().extract_calls(f)
        assert any(c["name"] == "bar" for c in calls)

    def test_parse_union_members_optional(self) -> None:
        from impactguard.languages.python import PythonExtractor
        result = PythonExtractor().parse_union_members("Optional[str]")
        assert result == frozenset({"str", "None"})

    def test_parse_union_members_union(self) -> None:
        from impactguard.languages.python import PythonExtractor
        result = PythonExtractor().parse_union_members("Union[int, str]")
        assert result == frozenset({"int", "str"})

    def test_parse_union_members_pep604(self) -> None:
        from impactguard.languages.python import PythonExtractor
        result = PythonExtractor().parse_union_members("int | None")
        assert result == frozenset({"int", "None"})

    def test_parse_union_members_scalar(self) -> None:
        from impactguard.languages.python import PythonExtractor
        result = PythonExtractor().parse_union_members("int")
        assert result == frozenset({"int"})

    def test_extensions(self) -> None:
        from impactguard.languages.python import PythonExtractor
        assert ".py" in PythonExtractor().extensions

    def test_empty_file(self, tmp_path: Path) -> None:
        f = _write(tmp_path, "empty.py", "")
        from impactguard.languages.python import PythonExtractor
        sigs = PythonExtractor().extract_signatures([str(f)])
        assert sigs == []

    def test_nonexistent_file(self) -> None:
        from impactguard.languages.python import PythonExtractor
        sigs = PythonExtractor().extract_signatures(["/nonexistent/path/file.py"])
        assert sigs == []


# ── TypeScript extractor (tree-sitter path) ───────────────────────────────────


class TestTypeScriptExtractorTreeSitter:
    """Tests that exercise the tree-sitter backend directly."""

    @pytest.fixture
    def ts_ext(self):
        from impactguard.languages.typescript import TypeScriptExtractor, _TREE_SITTER_AVAILABLE
        if not _TREE_SITTER_AVAILABLE:
            pytest.skip("tree-sitter-typescript not installed")
        return TypeScriptExtractor()

    def test_basic_function(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "api.ts", "function greet(name: string): void {}\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert len(sigs) == 1
        sig = sigs[0]
        assert sig["name"] == "greet"
        assert sig["fqname"] == "api.ts:greet"
        assert sig["positional"][0]["name"] == "name"
        assert sig["positional"][0]["type"] == "string"
        assert sig["positional"][0]["has_default"] is False
        assert sig["return_type"] == "void"
        assert sig["is_async"] is False

    def test_async_function(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "svc.ts", "async function fetch(url: string): Promise<string> {}\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert len(sigs) == 1
        assert sigs[0]["is_async"] is True

    def test_optional_parameter(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "api.ts", "function foo(a: string, b?: number): void {}\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs[0]["positional"][0]["has_default"] is False
        assert sigs[0]["positional"][1]["has_default"] is True

    def test_default_parameter(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "api.ts", "function bar(x: number = 5): void {}\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs[0]["positional"][0]["has_default"] is True

    def test_rest_parameter(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "api.ts", "function baz(...args: string[]): void {}\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs[0]["vararg"] is True
        assert sigs[0]["kwarg"] is False

    def test_class_method(self, tmp_path: Path, ts_ext) -> None:
        src = "class MyClass { doThing(x: string): number { return 0; } }\n"
        f = _write(tmp_path, "cls.ts", src)
        sigs = ts_ext.extract_signatures([str(f)])
        assert len(sigs) == 1
        assert sigs[0]["class_name"] == "MyClass"
        assert sigs[0]["name"] == "MyClass.doThing"
        assert sigs[0]["fqname"] == "cls.ts:MyClass.doThing"

    def test_async_class_method(self, tmp_path: Path, ts_ext) -> None:
        src = "class Svc { async fetch(url: string): Promise<void> {} }\n"
        f = _write(tmp_path, "svc.ts", src)
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs[0]["is_async"] is True

    def test_exported_function(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "api.ts", "export function pub(x: number): string { return ''; }\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs[0]["exported"] is True

    def test_non_exported_function(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "api.ts", "function priv(x: number): string { return ''; }\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs[0]["exported"] is False

    def test_arrow_function(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "fn.ts", "const double = (n: number): number => n * 2;\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert len(sigs) == 1
        assert sigs[0]["name"] == "double"
        assert sigs[0]["positional"][0]["name"] == "n"

    def test_decorator(self, tmp_path: Path, ts_ext) -> None:
        src = "class C {\n  @log\n  run(x: string): void {}\n}\n"
        f = _write(tmp_path, "dec.ts", src)
        sigs = ts_ext.extract_signatures([str(f)])
        assert "log" in sigs[0]["decorators"]

    def test_ignore_comment(self, tmp_path: Path, ts_ext) -> None:
        src = "// impactguard: ignore\nfunction hidden(x: number): void {}\n"
        f = _write(tmp_path, "ig.ts", src)
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs[0]["ignored"] is True

    def test_multiple_functions_sorted(self, tmp_path: Path, ts_ext) -> None:
        src = "function zzz(): void {}\nfunction aaa(): void {}\n"
        f = _write(tmp_path, "multi.ts", src)
        sigs = ts_ext.extract_signatures([str(f)])
        names = [s["name"] for s in sigs]
        assert names == sorted(names)

    def test_empty_file(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "empty.ts", "")
        sigs = ts_ext.extract_signatures([str(f)])
        assert sigs == []

    def test_nonexistent_file(self, ts_ext) -> None:
        sigs = ts_ext.extract_signatures(["/no/such/file.ts"])
        assert sigs == []

    def test_extract_calls(self, tmp_path: Path, ts_ext) -> None:
        src = "foo(a, b);\nobj.bar(c);\n"
        f = _write(tmp_path, "calls.ts", src)
        calls = ts_ext.extract_calls(f)
        names = [c["name"] for c in calls]
        assert "foo" in names
        assert "bar" in names

    def test_extract_calls_arg_count(self, tmp_path: Path, ts_ext) -> None:
        src = "greet('Alice', 42);\n"
        f = _write(tmp_path, "calls.ts", src)
        calls = ts_ext.extract_calls(f)
        greet_calls = [c for c in calls if c["name"] == "greet"]
        assert greet_calls[0]["args"] == 2

    def test_tsx_extension(self, tmp_path: Path, ts_ext) -> None:
        f = _write(tmp_path, "comp.tsx", "function render(props: object): string { return ''; }\n")
        sigs = ts_ext.extract_signatures([str(f)])
        assert len(sigs) == 1


# ── TypeScript extractor (regex fallback) ─────────────────────────────────────


class TestTypeScriptExtractorRegexFallback:
    """Tests targeting the regex-based fallback path explicitly."""

    @pytest.fixture
    def ts_regex(self):
        """Return TypeScript extractor with tree-sitter patched out."""
        import impactguard.languages.typescript as ts_mod
        with patch.object(ts_mod, "_TREE_SITTER_AVAILABLE", False):
            from impactguard.languages.typescript import TypeScriptExtractor
            yield TypeScriptExtractor()

    def test_basic_function(self, tmp_path: Path, ts_regex) -> None:
        f = _write(tmp_path, "api.ts", "function greet(name: string): void {}\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sigs = ts_regex.extract_signatures([str(f)])
        names = [s["name"] for s in sigs]
        assert "greet" in names

    def test_async_function(self, tmp_path: Path, ts_regex) -> None:
        f = _write(tmp_path, "a.ts", "async function load(url: string): Promise<void> {}\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sigs = ts_regex.extract_signatures([str(f)])
        assert any(s["is_async"] for s in sigs)

    def test_arrow_function(self, tmp_path: Path, ts_regex) -> None:
        f = _write(tmp_path, "a.ts", "const double = (n: number): number => n * 2;\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sigs = ts_regex.extract_signatures([str(f)])
        names = [s["name"] for s in sigs]
        assert "double" in names

    def test_optional_param_regex(self, tmp_path: Path, ts_regex) -> None:
        f = _write(tmp_path, "a.ts", "function foo(a: string, b?: number): void {}\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sigs = ts_regex.extract_signatures([str(f)])
        sig = next(s for s in sigs if s["name"] == "foo")
        opt = next(p for p in sig["positional"] if p["name"] == "b")
        assert opt["has_default"] is True

    def test_rest_param_regex(self, tmp_path: Path, ts_regex) -> None:
        f = _write(tmp_path, "a.ts", "function baz(...args: string[]): void {}\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sigs = ts_regex.extract_signatures([str(f)])
        assert any(s["vararg"] for s in sigs)

    def test_warns_when_tree_sitter_missing(self, tmp_path: Path) -> None:
        import impactguard.languages.typescript as ts_mod
        from impactguard.languages.typescript import TypeScriptExtractor
        f = _write(tmp_path, "a.ts", "function f(): void {}\n")
        inst = TypeScriptExtractor()  # fresh instance — _warned starts False
        with patch.object(ts_mod, "_TREE_SITTER_AVAILABLE", False):
            with pytest.warns(UserWarning, match="tree-sitter"):
                inst.extract_signatures([str(f)])

    def test_no_double_warn(self, tmp_path: Path) -> None:
        """Warning fires at most once per extractor instance."""
        import impactguard.languages.typescript as ts_mod
        from impactguard.languages.typescript import TypeScriptExtractor
        f = _write(tmp_path, "a.ts", "function f(): void {}\n")
        inst = TypeScriptExtractor()  # fresh instance — _warned starts False
        with patch.object(ts_mod, "_TREE_SITTER_AVAILABLE", False):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                inst.extract_signatures([str(f)])
                inst.extract_signatures([str(f)])  # second call
        user_warns = [x for x in w if issubclass(x.category, UserWarning)]
        assert len(user_warns) == 1

    def test_nonexistent_file_regex(self, ts_regex) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sigs = ts_regex.extract_signatures(["/no/such.ts"])
        assert sigs == []

    def test_extract_calls_regex(self, tmp_path: Path, ts_regex) -> None:
        src = "foo(a, b);\nbar();\n"
        f = _write(tmp_path, "calls.ts", src)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            calls = ts_regex.extract_calls(f)
        names = [c["name"] for c in calls]
        assert "foo" in names

    def test_parse_union_members(self) -> None:
        from impactguard.languages.typescript import TypeScriptExtractor
        ext = TypeScriptExtractor()
        assert ext.parse_union_members("string | null") == frozenset({"string", "null"})
        assert ext.parse_union_members("number") == frozenset({"number"})
        assert ext.parse_union_members("string | null | undefined") == frozenset(
            {"string", "null", "undefined"}
        )


# ── TypeScript regex helpers ───────────────────────────────────────────────────


class TestTypeScriptRegexHelpers:
    def test_parse_params_basic(self) -> None:
        from impactguard.languages.typescript import _parse_ts_params_regex
        pos, vararg = _parse_ts_params_regex("a: string, b: number")
        assert len(pos) == 2
        assert pos[0] == {"name": "a", "has_default": False, "type": "string"}
        assert pos[1] == {"name": "b", "has_default": False, "type": "number"}
        assert vararg is False

    def test_parse_params_optional(self) -> None:
        from impactguard.languages.typescript import _parse_ts_params_regex
        pos, _ = _parse_ts_params_regex("a: string, b?: number")
        assert pos[1]["has_default"] is True

    def test_parse_params_default(self) -> None:
        from impactguard.languages.typescript import _parse_ts_params_regex
        pos, _ = _parse_ts_params_regex("x: number = 5")
        assert pos[0]["has_default"] is True

    def test_parse_params_rest(self) -> None:
        from impactguard.languages.typescript import _parse_ts_params_regex
        pos, vararg = _parse_ts_params_regex("...args: string[]")
        assert vararg is True
        assert len(pos) == 0

    def test_parse_params_empty(self) -> None:
        from impactguard.languages.typescript import _parse_ts_params_regex
        pos, vararg = _parse_ts_params_regex("")
        assert pos == []
        assert vararg is False

    def test_top_level_split(self) -> None:
        from impactguard.languages.typescript import _top_level_split
        # Should not split inside angle brackets
        parts = _top_level_split("a: Map<string, number>, b: string")
        assert len(parts) == 2

    def test_top_level_split_nested_parens(self) -> None:
        from impactguard.languages.typescript import _top_level_split
        parts = _top_level_split("cb: (x: string) => void, y: number")
        assert len(parts) == 2


# ── TypeScript type compat in compare_signatures ──────────────────────────────


class TestTypeScriptTypeCompat:
    """Tests for the language-aware type comparison path in compare()."""

    def _write_sigs(self, tmp_path: Path, name: str, sigs: list[dict]) -> str:
        p = tmp_path / name
        p.write_text(json.dumps(sigs), encoding="utf-8")
        return str(p)

    def _make_sig(self, fqname: str, args: list[dict], return_type: str | None = None) -> dict:
        return {
            "fqname": fqname,
            "name": fqname.split(":")[-1],
            "positional": args,
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
            "exported": True,
        } | ({"return_type": return_type} if return_type else {})

    def test_typescript_widening_null(self, tmp_path: Path) -> None:
        """string → string | null is widening in TypeScript (non-breaking)."""
        from impactguard.compare_signatures import compare
        old_sig = self._make_sig("f.ts:fn", [{"name": "x", "has_default": False, "type": "string"}])
        new_sig = self._make_sig("f.ts:fn", [{"name": "x", "has_default": False, "type": "string | null"}])
        old_path = self._write_sigs(tmp_path, "old.json", [old_sig])
        new_path = self._write_sigs(tmp_path, "new.json", [new_sig])
        result = compare(old_path, new_path, language="typescript")
        assert any("TYPE WIDENED" in c for c in result["nonbreaking"])
        assert not any("TYPE CHANGED" in c for c in result["breaking"])

    def test_typescript_narrowing_null(self, tmp_path: Path) -> None:
        """string | null → string is narrowing (breaking)."""
        from impactguard.compare_signatures import compare
        old_sig = self._make_sig("f.ts:fn", [{"name": "x", "has_default": False, "type": "string | null"}])
        new_sig = self._make_sig("f.ts:fn", [{"name": "x", "has_default": False, "type": "string"}])
        old_path = self._write_sigs(tmp_path, "old.json", [old_sig])
        new_path = self._write_sigs(tmp_path, "new.json", [new_sig])
        result = compare(old_path, new_path, language="typescript")
        assert any("TYPE CHANGED" in c for c in result["breaking"])

    def test_python_compat_unchanged(self, tmp_path: Path) -> None:
        """Without language param, Python union parsing is used (backward compat)."""
        from impactguard.compare_signatures import compare
        old_sig = self._make_sig("m.py:fn", [{"name": "x", "has_default": False, "type": "int"}])
        new_sig = self._make_sig("m.py:fn", [{"name": "x", "has_default": False, "type": "int | None"}])
        old_path = self._write_sigs(tmp_path, "old.json", [old_sig])
        new_path = self._write_sigs(tmp_path, "new.json", [new_sig])
        result = compare(old_path, new_path)  # no language param
        assert any("TYPE WIDENED" in c for c in result["nonbreaking"])

    def test_unknown_language_falls_back_to_python(self, tmp_path: Path) -> None:
        """An unregistered language name falls back to Python union parsing."""
        from impactguard.compare_signatures import compare
        old_sig = self._make_sig("m.py:fn", [{"name": "x", "has_default": False, "type": "int"}])
        new_sig = self._make_sig("m.py:fn", [{"name": "x", "has_default": False, "type": "int | None"}])
        old_path = self._write_sigs(tmp_path, "old.json", [old_sig])
        new_path = self._write_sigs(tmp_path, "new.json", [new_sig])
        result = compare(old_path, new_path, language="nonexistent_lang")
        # Falls back to Python behaviour — int | None → widening
        assert any("TYPE WIDENED" in c for c in result["nonbreaking"])

    def test_return_type_widening_typescript(self, tmp_path: Path) -> None:
        from impactguard.compare_signatures import compare
        old_sig = self._make_sig("f.ts:fn", [], return_type="string")
        new_sig = self._make_sig("f.ts:fn", [], return_type="string | undefined")
        old_path = self._write_sigs(tmp_path, "old.json", [old_sig])
        new_path = self._write_sigs(tmp_path, "new.json", [new_sig])
        result = compare(old_path, new_path, language="typescript")
        assert any("RETURN TYPE WIDENED" in c for c in result["nonbreaking"])


# ── _type_change_kind with union_parser ───────────────────────────────────────


class TestTypeChangeKindWithParser:
    @staticmethod
    def _ts_parse(type_str: str) -> frozenset[str]:
        """Simple TypeScript-style union parser for tests."""
        return frozenset(p.strip() for p in type_str.split("|"))

    def test_custom_parser_widening(self) -> None:
        from impactguard.compare_signatures import _type_change_kind
        assert _type_change_kind("string", "string | null", self._ts_parse) == "widening"

    def test_custom_parser_narrowing(self) -> None:
        from impactguard.compare_signatures import _type_change_kind
        assert _type_change_kind("string | null", "string", self._ts_parse) == "narrowing"

    def test_no_parser_uses_python_defaults(self) -> None:
        from impactguard.compare_signatures import _type_change_kind
        # int → int | None is widening with the default Python parser
        assert _type_change_kind("int", "int | None") == "widening"

    def test_changed_incompatible_types(self) -> None:
        from impactguard.compare_signatures import _type_change_kind
        assert _type_change_kind("number", "string", self._ts_parse) == "changed"


# ── Config defaults for languages section ────────────────────────────────────


class TestLanguagesConfig:
    def test_languages_enabled_default(self) -> None:
        from impactguard.config import load_config
        cfg = load_config()
        langs_cfg = cfg.get("impactguard", {}).get("languages", {})
        assert "python" in langs_cfg.get("enabled", [])
        assert "typescript" in langs_cfg.get("enabled", [])

    def test_extension_overrides_default_empty(self) -> None:
        from impactguard.config import load_config
        cfg = load_config()
        overrides = cfg.get("impactguard", {}).get("languages", {}).get("extension_overrides", {})
        assert isinstance(overrides, dict)

    def test_languages_section_accessible_via_get(self) -> None:
        from impactguard.config import get
        enabled = get("languages", "enabled", [])
        assert "python" in enabled


# ── CLI --language flag ───────────────────────────────────────────────────────


class TestCLILanguageFlag:
    def test_extract_python_files(self, tmp_path: Path, capsys) -> None:
        f = _write(tmp_path, "m.py", "def foo(): pass\n")
        from impactguard.__main__ import cmd_extract
        import argparse
        args = argparse.Namespace(files=[str(f)], language=None)
        rc = cmd_extract(args)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert any(s["name"] == "foo" for s in data)

    def test_extract_with_explicit_language(self, tmp_path: Path, capsys) -> None:
        f = _write(tmp_path, "m.py", "def bar(): pass\n")
        from impactguard.__main__ import cmd_extract
        import argparse
        args = argparse.Namespace(files=[str(f)], language="python")
        rc = cmd_extract(args)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert any(s["name"] == "bar" for s in data)

    def test_extract_unknown_language_returns_error(self, tmp_path: Path, capsys) -> None:
        f = _write(tmp_path, "m.py", "def foo(): pass\n")
        from impactguard.__main__ import cmd_extract
        import argparse
        args = argparse.Namespace(files=[str(f)], language="cobol")
        rc = cmd_extract(args)
        assert rc == 1

    def test_extract_no_files_returns_error(self, capsys) -> None:
        from impactguard.__main__ import cmd_extract
        import argparse
        # Patch stdin to avoid blocking
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            args = argparse.Namespace(files=[], language=None)
            rc = cmd_extract(args)
        assert rc == 1

    def test_extract_unknown_extension_warns(self, tmp_path: Path, capsys) -> None:
        f = _write(tmp_path, "script.rb", "def foo; end\n")
        from impactguard.__main__ import cmd_extract
        import argparse
        args = argparse.Namespace(files=[str(f)], language=None)
        rc = cmd_extract(args)
        assert rc == 0  # Still succeeds, just skips unknown files
        err = capsys.readouterr().err
        assert "no extractor" in err.lower() or "warning" in err.lower()

    def test_extract_calls_python(self, tmp_path: Path, capsys) -> None:
        f = _write(tmp_path, "m.py", "bar(1, 2)\n")
        from impactguard.__main__ import cmd_extract_calls
        import argparse
        args = argparse.Namespace(files=[str(f)], language=None)
        rc = cmd_extract_calls(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert any(c["name"] == "bar" for c in data)

    def test_extract_calls_unknown_language_returns_error(self, tmp_path: Path, capsys) -> None:
        f = _write(tmp_path, "m.py", "bar(1)\n")
        from impactguard.__main__ import cmd_extract_calls
        import argparse
        args = argparse.Namespace(files=[str(f)], language="cobol")
        rc = cmd_extract_calls(args)
        assert rc == 1

    def test_extract_calls_no_files_returns_error(self, capsys) -> None:
        from impactguard.__main__ import cmd_extract_calls
        import argparse
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            args = argparse.Namespace(files=[], language=None)
            rc = cmd_extract_calls(args)
        assert rc == 1

    def test_extract_typescript_via_registry(self, tmp_path: Path, capsys) -> None:
        from impactguard.languages.typescript import _TREE_SITTER_AVAILABLE
        if not _TREE_SITTER_AVAILABLE:
            pytest.skip("tree-sitter-typescript not installed")
        f = _write(tmp_path, "api.ts", "export function hello(name: string): void {}\n")
        from impactguard.__main__ import cmd_extract
        import argparse
        args = argparse.Namespace(files=[str(f)], language=None)
        rc = cmd_extract(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert any(s["name"] == "hello" for s in data)


# ── Public __init__ exports ───────────────────────────────────────────────────


class TestPublicExports:
    def test_language_extractor_exported(self) -> None:
        import impactguard
        assert hasattr(impactguard, "LanguageExtractor")

    def test_register_language_exported(self) -> None:
        import impactguard
        assert callable(impactguard.register_language)

    def test_get_extractor_exported(self) -> None:
        import impactguard
        assert callable(impactguard.get_extractor)

    def test_get_extractor_by_language_exported(self) -> None:
        import impactguard
        assert callable(impactguard.get_extractor_by_language)

    def test_detect_language_exported(self) -> None:
        import impactguard
        assert callable(impactguard.detect_language)

    def test_list_languages_exported(self) -> None:
        import impactguard
        assert callable(impactguard.list_languages)

    def test_list_language_extensions_exported(self) -> None:
        import impactguard
        assert callable(impactguard.list_language_extensions)
