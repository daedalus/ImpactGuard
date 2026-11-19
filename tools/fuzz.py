#!/usr/bin/env python3
"""Robustness fuzzer for ImpactGuard.

Throws malformed and pathological inputs at the main entry points and reports
every uncaught exception or unexpectedly slow call:

* ``compare``   -- malformed signature entries and JSON files
* ``extract``   -- adversarial source (NUL bytes, bad encodings, deep nesting,
                   long expression chains, many functions) for every language
* ``diff``      -- unified-diff edge cases (quoted paths, repeated files, ...)

Usage::

    python tools/fuzz.py                  # all suites
    python tools/fuzz.py compare diff     # selected suites
    python tools/fuzz.py --deep 50000     # nesting depth for deep payloads

Exit status is 1 when any failure was found.  Some failures are expected:
50k-deep nesting still raises ``RecursionError`` in a few signature
extractors; the pipeline isolates those per file.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

SLOW_SECONDS = 5.0

Failure = tuple[str, str]


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"


# ── compare ──────────────────────────────────────────────────────────────────


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


def fuzz_compare(workdir: Path, _depth: int) -> list[Failure]:
    from impactguard.compare_signatures import compare
    from impactguard.extract_signatures import extract

    src = workdir / "sample.py"
    src.write_text(SAMPLE_PY)
    base = extract([str(src)])
    fails: list[Failure] = []

    for label, mutate in SIGNATURE_MUTATIONS.items():
        for side in ("old", "new", "both"):
            old, new = copy.deepcopy(base), copy.deepcopy(base)
            targets = {"old": [old], "new": [new], "both": [old, new]}[side]
            for sigs in targets:
                for sig in sigs:
                    mutate(sig)
            try:
                compare(old, new, include_private=True)
            except Exception as exc:  # noqa: BLE001 - we report everything
                fails.append((f"compare {label}/{side}", _err(exc)))

    for label, content in BAD_JSON_FILES.items():
        path = workdir / f"{label}.json"
        path.write_text(content, encoding="utf-8")
        try:
            compare(str(path), str(path))
        except ValueError:
            pass  # clean, documented rejection
        except Exception as exc:  # noqa: BLE001
            fails.append((f"compare file:{label}", _err(exc)))

    try:
        compare(str(workdir / "missing.json"), str(workdir / "missing.json"))
    except (ValueError, OSError):
        pass
    except Exception as exc:  # noqa: BLE001
        fails.append(("compare file:missing", _err(exc)))
    return fails


# ── extract ──────────────────────────────────────────────────────────────────


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


def fuzz_extract(workdir: Path, depth: int) -> list[Failure]:
    from impactguard.languages.lib.registry import (
        get_extractor_by_language,
        list_languages,
    )

    fails: list[Failure] = []
    payloads = _source_payloads(depth)
    for lang in list_languages():
        extractor = get_extractor_by_language(lang)
        if extractor is None:
            continue
        ext = extractor.extensions[0]
        for name, data in payloads.items():
            path = workdir / f"{lang}_{name}{ext}"
            path.write_bytes(data)
            started = time.monotonic()
            for kind, call in (
                ("signatures", lambda p=path: extractor.extract_signatures([str(p)])),
                ("calls", lambda p=path: extractor.extract_calls(p)),
            ):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001
                    fails.append((f"extract {lang}/{name}/{kind}", _err(exc)))
            elapsed = time.monotonic() - started
            if elapsed > SLOW_SECONDS:
                fails.append((f"extract {lang}/{name}", f"slow: {elapsed:.1f}s"))
        for bad in (workdir / f"nope{ext}", workdir):
            try:
                extractor.extract_signatures([str(bad)])
            except Exception as exc:  # noqa: BLE001
                fails.append((f"extract {lang}/path:{bad.name}", _err(exc)))
    return fails


# ── diff ─────────────────────────────────────────────────────────────────────


def _hunk(old_path: str, new_path: str, old: str, new: str) -> str:
    return f"--- {old_path}\n+++ {new_path}\n@@ -1 +1 @@\n-{old}\n+{new}\n"


# (diff text, expected file keys or None to only check "no crash")
DIFF_CASES: dict[str, tuple[str, set[str] | None]] = {
    "quoted_unicode": (
        _hunk('"a/caf\\303\\251.py"', '"b/caf\\303\\251.py"', "def f(a): pass", "def f(a, b): pass"),
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
        _hunk('"a/../../etc/x.py"', '"b/../../etc/x.py"', "def f(a): pass", "def f(): pass"),
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
    "garbage_hunk": ("--- a/x.py\n+++ b/x.py\n@@ -99999999999 +1,-5 @@\n-x\n+y\n", None),
    "dash_comment": (
        "--- a/x.hs\n+++ b/x.hs\n@@ -1,2 +1,2 @@\n--- comment\n-f a = a\n+-- comment\n+f a b = a\n",
        None,
    ),
}


def fuzz_diff(_workdir: Path, _depth: int) -> list[Failure]:
    from impactguard.pipeline import _extract_diff_files, _parse_unified_diff

    fails: list[Failure] = []
    for label, (text, expected) in DIFF_CASES.items():
        try:
            parsed = _parse_unified_diff(text)
            if expected is not None and set(parsed) != expected:
                fails.append((f"diff {label}", f"got files {sorted(parsed)}, expected {sorted(expected)}"))
            _extract_diff_files(parsed)
        except Exception as exc:  # noqa: BLE001
            fails.append((f"diff {label}", _err(exc)))
    same = _parse_unified_diff(DIFF_CASES["same_file_twice"][0]).get("x.py", ("", ""))
    if "def f(a): pass" not in same[0]:
        fails.append(("diff same_file_twice", "first section of repeated file was lost"))
    return fails


# ── driver ───────────────────────────────────────────────────────────────────

SUITES: dict[str, Callable[[Path, int], list[Failure]]] = {
    "compare": fuzz_compare,
    "extract": fuzz_extract,
    "diff": fuzz_diff,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("suites", nargs="*", default=list(SUITES), help=f"suites to run: {', '.join(SUITES)} (default: all)")
    parser.add_argument("--deep", type=int, default=50_000, help="nesting depth for deep payloads")
    parser.add_argument("-v", "--verbose", action="store_true", help="show library warnings")
    args = parser.parse_args(argv)
    unknown = [s for s in args.suites if s not in SUITES]
    if unknown:
        parser.error(f"unknown suite(s): {', '.join(unknown)}")

    if not args.verbose:
        import logging

        logging.disable(logging.WARNING)
        warnings.simplefilter("ignore")
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115 - silence library chatter

    total: list[Failure] = []
    with tempfile.TemporaryDirectory(prefix="impactguard_fuzz_") as tmp:
        for name in args.suites:
            workdir = Path(tmp) / name
            workdir.mkdir()
            started = time.monotonic()
            fails = SUITES[name](workdir, args.deep)
            print(f"[{name}] {len(fails)} failure(s) in {time.monotonic() - started:.1f}s")
            for label, detail in fails:
                print(f"  {label}: {detail}")
            total.extend(fails)
    print(f"TOTAL: {len(total)} failure(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
