"""Shared payloads, constants and helpers for the ImpactGuard fuzzer."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

SLOW_SECONDS = 5.0

# Repository root (tools/fuzzkit/corpus.py -> repo).
REPO = Path(__file__).resolve().parent.parent.parent

Failure = tuple[str, str]


def require_extractor(lang: str) -> Any:
    """Return the registered extractor for *lang*.

    Raises ``RuntimeError`` rather than using ``assert``, so the check also
    holds under ``python -O``.
    """
    from impactguard.languages.lib.registry import get_extractor_by_language

    extractor = get_extractor_by_language(lang)
    if extractor is None:
        raise RuntimeError(f"no extractor registered for language {lang!r}")
    return extractor


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"


# ── fixed payloads ──────────────────────────────────────────────────────────


def _set(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    return lambda s: s.__setitem__(key, copy.deepcopy(value))


def _set_args(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(s: dict[str, Any]) -> None:
        for arg in s.get("positional") or []:
            if isinstance(arg, dict):
                arg[key] = copy.deepcopy(value)

    return mutate


def _drop_args(key: str) -> Callable[[dict[str, Any]], None]:
    def mutate(s: dict[str, Any]) -> None:
        for arg in s.get("positional") or []:
            if isinstance(arg, dict):
                arg.pop(key, None)

    return mutate


SIGNATURE_MUTATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "fqname_list": _set("fqname", ["x"]),
    "fqname_none": _set("fqname", None),
    "fqname_int": _set("fqname", 5),
    "positional_none": _set("positional", None),
    "positional_str": _set("positional", "abc"),
    "positional_dict": _set("positional", {"a": 1}),
    "kwonly_none": _set("kwonly", None),
    "arg_is_str": _set("positional", ["a", "b"]),
    "arg_is_none": _set("positional", [None]),
    "arg_missing_default": _drop_args("has_default"),
    "arg_missing_name": _drop_args("name"),
    "has_default_str": _set_args("has_default", "false"),
    "type_int": _set_args("type", 5),
    "type_dict": _set_args("type", {}),
    "type_unbalanced": _set_args("type", "Dict[str, int]]]] | (("),
    "type_huge_union": _set_args("type", " | ".join(["A"] * 100_000)),
    "type_deep": _set_args("type", "List[" * 5000 + "int" + "]" * 5000),
    "return_int": _set("return_type", 5),
    "return_list": _set("return_type", ["int"]),
    "return_deep": _set("return_type", "Union[" * 3000 + "int" + "]" * 3000),
    "decorators_none": _set("decorators", None),
    "decorators_mixed": _set("decorators", [1, None, "x"]),
    "decorators_str": _set("decorators", "deprecated"),
    "vararg_dict": _set("vararg", {"x": 1}),
    "kwarg_list": _set("kwarg", [1]),
    "name_none": _set("name", None),
    "name_list": _set("name", ["a"]),
    "ignored_str": _set("ignored", "no"),
    "exported_str": _set("exported", "false"),
}

BAD_JSON_FILES = {
    "not_list": '{"a": 1}',
    "junk_items": '[null, 1, "x"]',
    "nan_fqname": '[{"fqname": NaN}]',
    "empty": "",
    "bom": "﻿[]",
    "deep": "[" * 100_000 + "]" * 100_000,
}

SAMPLE_PY = """
def f(a: int, b: str = "x", *args, c, d=1, **kw) -> int: ...
class C:
    @deprecated
    def m(self, x: list[int] | None): ...
"""


def _source_payloads(depth: int) -> dict[str, bytes]:
    return {
        "empty": b"",
        "nul": b"\x00\x00def f(): pass\x00",
        "invalid_utf8": b"\xff\xfe\xfa def f(a): pass\n",
        "latin1": "def caf\xe9(x): pass\n".encode("latin-1"),
        "utf16_bom": "def f(x): pass\n".encode("utf-16"),
        "utf8_bom": b"\xef\xbb\xbfdef f(x): pass\n",
        "crlf": b"def f(x):\r\n  pass\r\n",
        "lone_cr": b"def f(x):\r  pass\r",
        "form_feed": b"def f(x): pass\n\x0c\ndef g(y): pass\n",
        "unclosed": b"def f(a, b\nfunc g(\nfn h(\nint k(\n",
        "deep_parens": b"x = " + b"(" * depth + b"1" + b")" * depth + b"\n",
        "deep_brace": b"{" * depth + b"\n",
        "long_chain": b"x = " + b" + ".join([b"1"] * 3000) + b";\n",
        "long_params": b"def f("
        + b",".join(b"a%d" % i for i in range(20_000))
        + b"): pass\n",
        "many_funcs": b"".join(
            b"def f%d(a): pass\nfunction g%d(a) {}\nfn h%d(a: i32) {}\n" % (i, i, i)
            for i in range(3000)
        ),
        "unicode_names": "def ф(а): pass\nfunction α(β) {}\n".encode(),
        "ignore_variants": b"# IMPACTGUARD   :   IGNORE\n// impactguard:ignore\ndef f(): pass\n",
    }


def _hunk(old_path: str, new_path: str, old: str, new: str) -> str:
    return f"--- {old_path}\n+++ {new_path}\n@@ -1 +1 @@\n-{old}\n+{new}\n"


# (diff text, expected file keys or None to only check "no crash")
DIFF_CASES: dict[str, tuple[str, set[str] | None]] = {
    "quoted_unicode": (
        _hunk(
            '"a/caf\\303\\251.py"',
            '"b/caf\\303\\251.py"',
            "def f(a): pass",
            "def f(a, b): pass",
        ),
        {"café.py"},
    ),
    "quoted_space": (
        _hunk('"a/my mod.py"', '"b/my mod.py"', "def f(a): pass", "def f(): pass"),
        {"my mod.py"},
    ),
    "unquoted_space": (
        _hunk("a/my mod.py", "b/my mod.py", "def f(a): pass", "def f(): pass"),
        {"my mod.py"},
    ),
    "traversal": (
        _hunk(
            '"a/../../etc/x.py"',
            '"b/../../etc/x.py"',
            "def f(a): pass",
            "def f(): pass",
        ),
        set(),
    ),
    "absolute": (
        _hunk("/etc/x.py", "/etc/x.py", "def f(a): pass", "def f(): pass"),
        set(),
    ),
    "same_file_twice": (
        _hunk("a/x.py", "b/x.py", "def f(a): pass", "def f(a, b): pass")
        + _hunk("a/x.py", "b/x.py", "def g(a): pass", "def g(): pass"),
        {"x.py"},
    ),
    "file_then_dir": (
        _hunk("a/a.py", "b/a.py", "def f(): pass", "def f(x): pass")
        + _hunk("a/a.py/b.py", "b/a.py/b.py", "def g(): pass", "def g(x): pass"),
        None,
    ),
    "binary": ("Binary files a/x.py and b/x.py differ\n", set()),
    "garbage_hunk": (
        "--- a/x.py\n+++ b/x.py\n@@ -99999999999 +1,-5 @@\n-x\n+y\n",
        None,
    ),
    "dash_comment": (
        "--- a/x.hs\n+++ b/x.hs\n@@ -1,2 +1,2 @@\n--- comment\n-f a = a\n+-- comment\n+f a b = a\n",
        None,
    ),
}
