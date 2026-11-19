#!/usr/bin/env python3
"""Robustness fuzzer for ImpactGuard.

Throws malformed and pathological inputs at the main entry points and reports
every uncaught exception or unexpectedly slow call:

* ``compare``   -- malformed signature entries and JSON files
* ``extract``   -- adversarial source (NUL bytes, bad encodings, deep nesting,
                   long expression chains, many functions) for every language
* ``diff``      -- unified-diff edge cases (quoted paths, repeated files, ...)
* ``mutate``    -- seeded mutation fuzzing: random byte/text/structure
                   mutations of real sources, diffs and signature JSON,
                   checked against crash, schema, path-safety and
                   slowness oracles, plus ``regress`` mutators that
                   regenerate every known past bug with random parameters
                   and check metamorphic oracles (e.g. a form feed inside
                   a comment must not move ignore flags)

Usage::

    python tools/fuzz.py                  # all suites
    python tools/fuzz.py compare diff     # selected suites
    python tools/fuzz.py --deep 50000     # nesting depth for deep payloads
    python tools/fuzz.py mutate --iterations 20000 --seed 1234
    python tools/fuzz.py mutate --kinds regress --iterations 500
    python tools/fuzz.py --replay fuzz-crashes/diff__0123456789ab.diff

Exit status is 1 when any failure was found.  Known, accepted findings:

* ``deep_parens``/``long_chain`` signatures in the C, C++, Rust, Ruby,
  TypeScript and Haskell extractors raise ``RecursionError`` -- these
  payloads are syntax errors in those languages and tree-sitter's error
  recovery builds very deep trees.  The pipeline isolates such files and
  records a parse failure instead of aborting.
* ``many_funcs`` is "slow" for some languages: the time is spent inside
  tree-sitter's C parser recovering from mixed-language garbage.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import functools
import hashlib
import json
import os
import random
import sys
import tempfile
import time
import traceback
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

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


def fuzz_compare(workdir: Path, _opts: argparse.Namespace) -> list[Failure]:
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


def fuzz_extract(workdir: Path, opts: argparse.Namespace) -> list[Failure]:
    from impactguard.languages.lib.registry import (
        get_extractor_by_language,
        list_languages,
    )

    fails: list[Failure] = []
    payloads = _source_payloads(opts.deep)
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


def fuzz_diff(_workdir: Path, _opts: argparse.Namespace) -> list[Failure]:
    from impactguard.pipeline import _extract_diff_files, _parse_unified_diff

    fails: list[Failure] = []
    for label, (text, expected) in DIFF_CASES.items():
        try:
            parsed = _parse_unified_diff(text)
            if expected is not None and set(parsed) != expected:
                fails.append(
                    (
                        f"diff {label}",
                        f"got files {sorted(parsed)}, expected {sorted(expected)}",
                    )
                )
            _extract_diff_files(parsed)
        except Exception as exc:  # noqa: BLE001
            fails.append((f"diff {label}", _err(exc)))
    same = _parse_unified_diff(DIFF_CASES["same_file_twice"][0]).get("x.py", ("", ""))
    if "def f(a): pass" not in same[0]:
        fails.append(
            ("diff same_file_twice", "first section of repeated file was lost")
        )
    return fails


# ── mutate: seeded mutation-based fuzzing ────────────────────────────────────
#
# Start from *valid* inputs (example sources, diffs built from them, extracted
# signature JSON), apply random byte/text/structure mutations and check
# oracles.  Unlike the fixed payload suites above this explores the space
# around realistic input, so it finds bugs nobody thought to write a case for.
# Runs are deterministic for a given ``--seed``; crashing inputs are written to
# ``--crash-dir`` and can be re-run with ``--replay``.

REPO = Path(__file__).resolve().parent.parent

# Tokens that historically broke parsers or line accounting.
INTERESTING_TEXT = [
    "\x00",
    "\f",
    "\v",
    "\r",
    "\r\n",
    " ",
    "\x85",
    "﻿",
    "\t",
    '"',
    "'",
    "`",
    "\\",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "<",
    ">",
    ";",
    ",",
    "/*",
    "*/",
    "//",
    "#",
    "--",
    "\n\n",
    " ",
    "é",
    "\U0001f600",
    "# impactguard: ignore\n",
    "// impactguard: ignore\n",
    "-- impactguard: ignore\n",
    "def ",
    "function ",
    "fn ",
    "func ",
    "class ",
    "export ",
    "pub ",
    "static ",
    "@deprecated\n",
    "...",
    "=",
    "=>",
    "->",
    "::",
    "*",
    "**",
    "&",
    "|",
    "?",
]
INTERESTING_VALUES: list[Any] = [
    None,
    True,
    False,
    0,
    -1,
    2**63,
    1.5,
    float("nan"),
    float("inf"),
    "",
    "x",
    "a" * 10_000,
    [],
    [None],
    ["x"],
    {},
    {"name": None},
    {"name": "a"},
]
DIFF_INTERESTING_LINES = [
    "--- a/x.py",
    "+++ b/x.py",
    "--- /dev/null",
    "+++ /dev/null",
    '--- "a/caf\\303\\251.py"',
    '+++ "b/../../etc/evil.py"',
    "+++ /etc/passwd.py",
    "@@ -1 +1 @@",
    "@@ -0,0 +1,3 @@",
    "@@ -1,99999 +1,99999 @@",
    "@@ garbage @@",
    "Binary files a/x.py and b/x.py differ",
    "\\ No newline at end of file",
    "diff --git a/x.py b/x.py",
    "rename from x.py",
    "rename to ../y.py",
    "-",
    "+",
    " ",
    "--- ",
    "+++ ",
]


def _rand_span(rng: random.Random, n: int) -> tuple[int, int]:
    if n == 0:
        return 0, 0
    start = rng.randrange(n)
    return start, min(n, start + rng.randint(1, max(1, min(64, n - start))))


def _mutate_text(rng: random.Random, text: str, seeds: list[str]) -> str:
    """Apply one random text-level mutation."""
    n = len(text)
    op = rng.randrange(12)
    pos = rng.randint(0, n)
    if op == 0:  # insert interesting token
        return text[:pos] + rng.choice(INTERESTING_TEXT) + text[pos:]
    if op == 1 and n:  # delete span
        a, b = _rand_span(rng, n)
        return text[:a] + text[b:]
    if op == 2 and n:  # duplicate span
        a, b = _rand_span(rng, n)
        return text[:b] + text[a:b] * rng.randint(1, 8) + text[b:]
    if op == 3:  # bracket / operator run
        tok = rng.choice(["(", "[", "{", "<", "(" * 2 + ")", " + 1", ".a()", "-"])
        return text[:pos] + tok * rng.randint(2, 400) + text[pos:]
    if op == 4:  # truncate
        return text[:pos]
    if op == 5:  # swap two lines
        lines = text.split("\n")
        if len(lines) > 1:
            i, j = rng.randrange(len(lines)), rng.randrange(len(lines))
            lines[i], lines[j] = lines[j], lines[i]
        return "\n".join(lines)
    if op == 6:  # duplicate a line many times
        lines = text.split("\n")
        if lines:
            i = rng.randrange(len(lines))
            lines[i:i] = [lines[i]] * rng.randint(1, 200)
        return "\n".join(lines)
    if op == 7 and seeds:  # splice with another seed
        other = rng.choice(seeds)
        return text[:pos] + other[rng.randint(0, len(other)) :]
    if op == 8 and n:  # replace a char with a random code point
        cp = rng.choice(
            [
                rng.randint(0, 0x7F),
                rng.randint(0x80, 0xFFFF),
                rng.randint(0x10000, 0x10FFFF),
            ]
        )
        ch = chr(cp) if not 0xD800 <= cp <= 0xDFFF else "?"
        return text[: pos % n] + ch + text[pos % n + 1 :]
    if op == 9:  # change line endings
        return text.replace("\n", rng.choice(["\r\n", "\r", "\n\f", " "]))
    if op == 10:  # strip indentation / whitespace
        return text.replace(rng.choice(["    ", "\t", " "]), "", rng.randint(1, 50))
    # op 11 (or fall-through): identifier/number clobber
    return (
        text[:pos]
        + rng.choice(["0", "9" * 40, "_", "a" * 300, "self", "None"])
        + text[pos:]
    )


def _mutate_bytes(rng: random.Random, data: bytes) -> bytes:
    """Apply one raw byte mutation (bit flip / random byte / bad encoding)."""
    if not data:
        return bytes([rng.randrange(256)])
    buf = bytearray(data)
    op = rng.randrange(3)
    i = rng.randrange(len(buf))
    if op == 0:
        buf[i] ^= 1 << rng.randrange(8)
    elif op == 1:
        buf[i:i] = rng.choice(
            [b"\xff", b"\xc3", b"\xe2\x80", b"\xed\xa0\x80", b"\x00", b"\xef\xbb\xbf"]
        )
    else:
        buf[i] = rng.randrange(256)
    return bytes(buf)


def _mutate_source(rng: random.Random, text: str, seeds: list[str]) -> bytes:
    for _ in range(rng.randint(1, 4)):
        text = _mutate_text(rng, text, seeds)
    data = text.encode("utf-8", errors="surrogatepass")
    if rng.random() < 0.25:
        data = _mutate_bytes(rng, data)
    return data


def _mutate_json_value(rng: random.Random, value: Any, depth: int = 0) -> Any:
    """Structure-aware mutation of decoded signature JSON."""
    if isinstance(value, dict) and value and depth < 4:
        out = dict(value)
        key = rng.choice(list(out))
        op = rng.randrange(4)
        if op == 0:
            del out[key]
        elif op == 1:
            out[key] = copy.deepcopy(rng.choice(INTERESTING_VALUES))
        else:
            out[key] = _mutate_json_value(rng, out[key], depth + 1)
        return out
    if isinstance(value, list) and value and depth < 4:
        out_list = list(value)
        i = rng.randrange(len(out_list))
        op = rng.randrange(4)
        if op == 0:
            del out_list[i]
        elif op == 1:
            out_list.insert(i, copy.deepcopy(out_list[i]))  # duplicate entry
        elif op == 2:
            out_list[i] = copy.deepcopy(rng.choice(INTERESTING_VALUES))
        else:
            out_list[i] = _mutate_json_value(rng, out_list[i], depth + 1)
        return out_list
    return copy.deepcopy(rng.choice(INTERESTING_VALUES))


def _mutate_diff(rng: random.Random, text: str, seeds: list[str]) -> str:
    lines = text.split("\n")
    for _ in range(rng.randint(1, 4)):
        op = rng.randrange(4)
        i = rng.randint(0, len(lines))
        if op == 0:
            lines.insert(i, rng.choice(DIFF_INTERESTING_LINES))
        elif op == 1 and lines:
            del lines[min(i, len(lines) - 1)]
        elif op == 2 and lines:
            j = min(i, len(lines) - 1)
            lines[j] = rng.choice("+- \\@") + lines[j][1:]  # flip line tag
        else:
            lines = _mutate_text(rng, "\n".join(lines), seeds).split("\n")
    return "\n".join(lines)


def _load_source_seeds() -> dict[str, list[str]]:
    """Seed corpus per language: examples/ plus ImpactGuard's own sources."""
    from impactguard.languages.lib.registry import get_extractor, list_languages

    seeds: dict[str, list[str]] = {lang: [] for lang in list_languages()}
    candidates = list((REPO / "examples").rglob("*")) + list(
        (REPO / "src").rglob("*.py")
    )
    for path in sorted(candidates):
        if not path.is_file() or path.stat().st_size > 200_000:
            continue
        extractor = get_extractor(str(path))
        if extractor is None or extractor.language not in seeds:
            continue
        try:
            seeds[extractor.language].append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    fallback = {
        "python": "def f(a, b=1, *args, c, **kw) -> int:\n    return g(a)\n",
        "javascript": "export function f(a, b = 1) { return g(a); }\n",
        "typescript": "export function f(a: number, b?: string): number { return g(a); }\n",
        "java": "class A { public int f(int a) { return g(a); } }\n",
        "kotlin": 'fun f(a: Int, b: String = "x"): Int = g(a)\n',
        "go": "package p\nfunc F(a int, b string) int { return g(a) }\n",
        "rust": "pub fn f(a: i32, b: &str) -> i32 { g(a) }\n",
        "swift": 'func f(a: Int, b: String = "x") -> Int { return g(a) }\n',
        "c": "int f(int a, const char *b) { return g(a); }\n",
        "cpp": "namespace n { int f(int a, int b = 1) { return g(a); } }\n",
        "csharp": "class A { public int F(int a, int b = 1) { return G(a); } }\n",
        "ruby": "def f(a, b = 1, *rest, key:, **opts)\n  g(a)\nend\n",
        "haskell": "f :: Int -> Int\nf a = g a\n",
        "zig": "pub fn f(a: i32, b: i32) i32 { return g(a); }\n",
    }
    for lang, corpus in seeds.items():
        if not corpus and lang in fallback:
            corpus.append(fallback[lang])
    return seeds


def _check_signatures(result: object) -> str | None:
    """Oracle: extractor output must keep the schema shape compare() relies on."""
    if not isinstance(result, list):
        return f"extract_signatures returned {type(result).__name__}, not list"
    for sig in result:
        if not isinstance(sig, dict):
            return f"signature is {type(sig).__name__}, not dict"
        if not isinstance(sig.get("fqname"), str) or not sig["fqname"]:
            return f"bad fqname {sig.get('fqname')!r}"
        for key in ("positional", "kwonly"):
            args = sig.get(key)
            if not isinstance(args, list) or not all(
                isinstance(a, dict) and isinstance(a.get("name"), str) for a in args
            ):
                return f"{sig['fqname']}: malformed {key!r}: {args!r:.80}"
    return None


def _check_calls(result: object) -> str | None:
    if not isinstance(result, list):
        return f"extract_calls returned {type(result).__name__}, not list"
    for call in result:
        if not isinstance(call, dict) or not isinstance(call.get("name"), str):
            return f"malformed call {call!r:.80}"
        if not isinstance(call.get("lineno"), int):
            return f"call {call['name']!r} has non-int lineno {call.get('lineno')!r}"
    return None


def _run_extract_target(lang: str, path: Path) -> str | None:
    from impactguard.languages.lib.registry import get_extractor_by_language

    extractor = get_extractor_by_language(lang)
    assert extractor is not None
    problem = _check_signatures(extractor.extract_signatures([str(path)]))
    if problem:
        return problem
    return _check_calls(extractor.extract_calls(path))


def _run_diff_target(text: str) -> str | None:
    from impactguard._pathutils import is_safe_path
    from impactguard.pipeline import _extract_diff_files, _parse_unified_diff

    parsed = _parse_unified_diff(text)
    for name in parsed:
        if not is_safe_path(name):  # security oracle
            return f"unsafe path escaped the diff parser: {name!r}"
    old_files, new_files, old_dir, new_dir = _extract_diff_files(parsed)
    for f in [*old_files, *new_files]:
        root = old_dir if f in old_files else new_dir
        if not Path(f).resolve().is_relative_to(root.resolve()):
            return f"file materialised outside temp dir: {f}"
    return None


def _run_compare_target(path: Path) -> str | None:
    from impactguard.compare_signatures import compare

    try:
        result = compare(str(path), str(path), include_private=True)
    except ValueError:
        return None  # documented rejection of an invalid file
    if result["breaking"]:
        return (
            f"identical snapshots reported breaking changes: {result['breaking'][:3]}"
        )
    return None


def _crash_key(exc: BaseException) -> str:
    """Deduplicate crashes by exception type and innermost ImpactGuard frame."""
    frames = [
        f
        for f in traceback.extract_tb(exc.__traceback__)
        if "impactguard" in f.filename
    ]
    where = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else "?"
    return f"{type(exc).__name__}@{where}"


def _save_crash(crash_dir: Path, target: str, ext: str, data: bytes) -> Path:
    crash_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:12]
    path = crash_dir / f"{target}__{digest}{ext}"
    path.write_bytes(data)
    return path


# ── regression mutators ──────────────────────────────────────────────────────
#
# Each past bug becomes a *targeted* mutator that regenerates the bug's
# triggering shape with random parameters, paired with an oracle.  Most
# oracles are metamorphic: the mutation must NOT change the analysis result
# (e.g. a form feed inside a comment must not move ignore flags), which
# catches silent false negatives that a crash-only oracle never sees.
#
# A mutator is ``fn(rng, workdir) -> check`` where ``check() -> str | None``
# returns a problem description.  Cases are rebuilt from (mutator, case_seed),
# so a saved reproducer is just that pair.

RegressionCheck = Callable[[], "str | None"]

# (comment prefix, function template, file header, file footer) per language.
# Templates use {name}; classes wrap methods for Java/C#.
LANG_TEMPLATES: dict[str, tuple[str, str, str, str]] = {
    "python": ("#", "def {name}(x, y=1):\n    return g(x)\n", "", ""),
    "ruby": ("#", "def {name}(x, y = 1)\n  g(x)\nend\n", "", ""),
    "c": ("//", "int {name}(int x, int y) {{ return g(x); }}\n", "", ""),
    "cpp": ("//", "int {name}(int x, int y) {{ return g(x); }}\n", "", ""),
    "go": (
        "//",
        "func {name}(x int, y int) int {{ return g(x) }}\n",
        "package p\n",
        "",
    ),
    "rust": ("//", "pub fn {name}(x: i32, y: i32) -> i32 {{ g(x) }}\n", "", ""),
    "javascript": (
        "//",
        "export function {name}(x, y = 1) {{ return g(x); }}\n",
        "",
        "",
    ),
    "typescript": (
        "//",
        "export function {name}(x: number, y?: number): number {{ return g(x); }}\n",
        "",
        "",
    ),
    "java": (
        "//",
        "  public int {name}(int x, int y) {{ return g(x); }}\n",
        "class A {\n",
        "}\n",
    ),
    "csharp": (
        "//",
        "  public int {name}(int x, int y) {{ return G(x); }}\n",
        "class A {\n",
        "}\n",
    ),
    "kotlin": ("//", "fun {name}(x: Int, y: Int = 1): Int {{ return g(x) }}\n", "", ""),
    "swift": (
        "//",
        "func {name}(x: Int, y: Int = 1) -> Int {{ return g(x) }}\n",
        "",
        "",
    ),
    "zig": ("//", "pub fn {name}(x: i32, y: i32) i32 {{ return g(x); }}\n", "", ""),
}

# Body statement holding a long ``1 + 1 + ...`` chain, per language.
CHAIN_FUNCS: dict[str, str] = {
    "python": "def chainfn(a):\n    s = {expr}\n    return g(a)\n",
    "ruby": "def chainfn(a)\n  s = {expr}\n  g(a)\nend\n",
    "c": "int chainfn(int a) {{ int s = {expr}; return g(a); }}\n",
    "cpp": "int chainfn(int a) {{ int s = {expr}; return g(a); }}\n",
    "go": "func chainfn(a int) int {{ s := {expr}; _ = s; return g(a) }}\n",
    "rust": "pub fn chainfn(a: i32) -> i32 {{ let s = {expr}; g(a) }}\n",
    "javascript": "export function chainfn(a) {{ const s = {expr}; return g(a); }}\n",
    "typescript": "export function chainfn(a: number): number {{ const s = {expr}; return g(a); }}\n",
    "java": "  public int chainfn(int a) {{ int s = {expr}; return g(a); }}\n",
    "csharp": "  public int chainfn(int a) {{ var s = {expr}; return G(a); }}\n",
    "kotlin": "fun chainfn(a: Int): Int {{ val s = {expr}\n return g(a) }}\n",
    "swift": "func chainfn(a: Int) -> Int {{ let s = {expr}\n return g(a) }}\n",
    "zig": "pub fn chainfn(a: i32) i32 {{ const s = {expr}; _ = s; return g(a); }}\n",
}

# Line separators that str.splitlines() honours but parsers do not.  JS/TS
# treat U+2028 as a real line terminator, so it is excluded there.
EXOTIC_SEPARATORS = ["\f", "\v", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]
JS_LIKE = {"javascript", "typescript"}

CHAINED_CALL_FUNCS: dict[str, str] = {
    "python": "def outer(a):\n    return g{calls}\n",
    "javascript": "export function outer(a) {{ return g{calls}; }}\n",
    "typescript": "export function outer(a: number) {{ return g{calls}; }}\n",
    "go": "func outer(a int) int {{ return g{calls} }}\n",
    "rust": "pub fn outer(a: i32) -> i32 {{ g{calls} }}\n",
    "c": "int outer(int a) {{ return g{calls}; }}\n",
    "cpp": "int outer(int a) {{ return g{calls}; }}\n",
}

_NAME_CHARS = "abcdefghijklmnopqrstuvwxyz"
_PATH_SPECIALS = [" ", "é", "日", '"', "\\", "-", "ü", "\t"]


def _rand_ident(rng: random.Random, prefix: str = "f") -> str:
    return prefix + "".join(rng.choice(_NAME_CHARS) for _ in range(rng.randint(3, 8)))


def _build_source(lang: str, names: list[str], ignored: set[str]) -> str:
    comment, template, header, footer = LANG_TEMPLATES[lang]
    parts = [header]
    for name in names:
        if name in ignored:
            parts.append(f"{comment} impactguard: ignore\n")
        parts.append(template.format(name=name))
    parts.append(footer)
    return "".join(parts)


def _extract_with(lang: str, path: Path) -> list[dict[str, Any]]:
    from impactguard.languages.lib.registry import get_extractor_by_language

    extractor = get_extractor_by_language(lang)
    assert extractor is not None
    return extractor.extract_signatures([str(path)])


def _sig_view(sigs: list[dict[str, Any]]) -> list[tuple[str, int, bool]]:
    return sorted(
        (s["fqname"], s.get("lineno", 0), bool(s.get("ignored"))) for s in sigs
    )


def _reg_ignore_separator(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Session bug: form feeds / U+2028 shifted lines so ignore comments
    attached to the wrong function.  Oracle: inserting an exotic separator
    *inside a comment* must not change (fqname, lineno, ignored)."""
    lang = rng.choice(sorted(LANG_TEMPLATES))
    names = [_rand_ident(rng) + str(i) for i in range(rng.randint(3, 7))]
    ignored = set(rng.sample(names, rng.randint(1, len(names) - 1)))
    base = _build_source(lang, names, ignored)
    comment = LANG_TEMPLATES[lang][0]
    seps = [s for s in EXOTIC_SEPARATORS if not (lang in JS_LIKE and s in "  ")]
    lines = base.split("\n")
    for _ in range(rng.randint(1, 4)):
        sep = rng.choice(seps)
        at = rng.randint(len(LANG_TEMPLATES[lang][2].split("\n")) - 1, len(lines) - 1)
        lines.insert(at, f"{comment} page{sep}break")
    mutated = "\n".join(lines)
    # Baseline gets the same comment lines without the separator so that
    # line numbers are comparable.
    plain = "\n".join(
        ln.replace("page", "page ").translate({ord(s): None for s in seps})
        if ln.startswith(f"{comment} page")
        else ln
        for ln in lines
    )
    ext = _ext_for(lang)

    def check() -> str | None:
        a, b = workdir / f"base{ext}", workdir / f"mut{ext}"
        a.write_text(plain, encoding="utf-8")
        b.write_text(mutated, encoding="utf-8")
        before = _sig_view(_extract_with(lang, a))
        after = [
            (f.replace("mut", "base", 1), ln, ig)
            for f, ln, ig in _sig_view(_extract_with(lang, b))
        ]
        if before != after:
            return f"{lang}: separator changed signatures/ignore flags: {before} != {after}"
        return None

    return check


def _ext_for(lang: str) -> str:
    from impactguard.languages.lib.registry import get_extractor_by_language

    extractor = get_extractor_by_language(lang)
    assert extractor is not None
    return extractor.extensions[0]


def _reg_long_chain(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Session bug: recursive tree walks overflowed on long expression
    chains.  Oracle: adding a function containing an N-term chain yields
    exactly the old signatures plus ``chainfn``."""
    lang = rng.choice(sorted(CHAIN_FUNCS))
    names = [_rand_ident(rng) + str(i) for i in range(rng.randint(1, 4))]
    base = _build_source(lang, names, set())
    header, footer = LANG_TEMPLATES[lang][2], LANG_TEMPLATES[lang][3]
    chain = CHAIN_FUNCS[lang].format(expr=" + ".join(["1"] * rng.randint(500, 4000)))
    body = (
        base[len(header) : len(base) - len(footer)] if footer else base[len(header) :]
    )
    mutated = header + body + chain + footer
    ext = _ext_for(lang)

    def check() -> str | None:
        a, b = workdir / f"base{ext}", workdir / f"base_chain{ext}"
        a.write_text(base)
        b.write_text(mutated)
        before = {s["name"] for s in _extract_with(lang, a)}
        after = {s["name"] for s in _extract_with(lang, b)}
        expected = before | {n for n in after if n.split(".")[-1] == "chainfn"}
        if after != expected or not any(n.split(".")[-1] == "chainfn" for n in after):
            return (
                f"{lang}: chain changed signatures: {sorted(before)} -> {sorted(after)}"
            )
        return None

    return check


def _has_grammar(lang: str) -> bool:
    """True when *lang*'s tree-sitter grammar is installed (else the
    extractor runs its regex fallback)."""
    import importlib.util

    module = {"csharp": "tree_sitter_c_sharp"}.get(lang, f"tree_sitter_{lang}")
    try:
        return importlib.util.find_spec("tree_sitter") is not None and (
            importlib.util.find_spec(module) is not None
        )
    except (ImportError, ValueError):
        return False


def _reg_chained_callee(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Session bug: ``g()()()...`` overflowed the call-name resolver.
    Oracle: no crash and every resolved call name is ``g``."""
    lang = rng.choice(sorted(CHAINED_CALL_FUNCS))
    src = CHAINED_CALL_FUNCS[lang].format(calls="()" * rng.randint(300, 6000))
    path = workdir / f"chained{_ext_for(lang)}"

    def check() -> str | None:
        from impactguard.languages.lib.registry import get_extractor_by_language

        path.write_text(LANG_TEMPLATES[lang][2] + src)
        extractor = get_extractor_by_language(lang)
        assert extractor is not None
        names = {c["name"] for c in extractor.extract_calls(path)}
        allowed = {"g"}
        if not _has_grammar(lang):
            # Without the tree-sitter grammar the regex fallback also
            # (lossily, by design) reports the ``outer(`` definition.
            allowed.add("outer")
        if names - allowed or "g" not in names:
            return f"{lang}: unexpected call names {sorted(names)[:5]}"
        return None

    return check


def _reg_python_parser_overflow(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Session bug: CPython's parser raises MemoryError/RecursionError on
    pathological nesting.  Oracle: the pipeline's group extraction and call
    extraction never let an exception escape."""
    shape = rng.choice(["-", "not ", "lambda: ", "1 if 1 else ", "+"])
    n = rng.randint(3000, 30000)
    src = "x = " + (" + ".join(["1"] * n) if shape == "+" else shape * n + "1") + "\n"
    path = workdir / "deep_overflow.py"

    def check() -> str | None:
        from impactguard.languages.lib.registry import get_extractor_by_language
        from impactguard.pipeline import _extract_group

        path.write_text(src)
        extractor = get_extractor_by_language("python")
        assert extractor is not None
        _extract_group(extractor, [str(path)], None, False, {}, [])
        extractor.extract_calls(path)
        return None

    return check


def _reg_group_isolation(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Session bug: one pathological file discarded every signature of its
    language group.  Oracle: all healthy files' signatures survive."""
    lang = rng.choice(sorted(LANG_TEMPLATES))
    ext = _ext_for(lang)
    healthy: list[str] = []
    expected: set[str] = set()
    for i in range(rng.randint(2, 5)):
        name = f"{_rand_ident(rng)}{i}"
        p = workdir / f"ok{i}{ext}"
        p.write_text(_build_source(lang, [name], set()))
        healthy.append(str(p))
        expected.add(name)
    bad = workdir / f"zz_bad{ext}"
    depth = rng.randint(20_000, 60_000)
    bad_src = rng.choice(
        ["(" * depth + ")" * depth, "x = " + "(" * depth + "1" + ")" * depth]
    )
    files = [*healthy, str(bad)]
    rng.shuffle(files)

    def check() -> str | None:
        from impactguard.languages.lib.registry import get_extractor_by_language
        from impactguard.pipeline import _extract_group

        bad.write_text(bad_src + "\n")
        extractor = get_extractor_by_language(lang)
        assert extractor is not None
        result = _extract_group(extractor, files, str(workdir), False, {}, [])
        found = {s["name"].split(".")[-1] for s in result}
        missing = expected - found
        return (
            f"{lang}: healthy signatures lost: {sorted(missing)}" if missing else None
        )

    return check


def _git_quote(path: str) -> str:
    """Quote *path* the way git does with ``core.quotePath=true``."""
    out = []
    for ch in path:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x80:
            out.append(ch)
        else:
            out.extend(f"\\{b:03o}" for b in ch.encode("utf-8"))
    return '"' + "".join(out) + '"'


def _make_diff(
    old_name: str, new_name: str, old: str, new: str, context: int = 3
) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=old_name,
            tofile=new_name,
            n=context,
        )
    )


def _rand_changed_python(rng: random.Random, n_funcs: int) -> tuple[str, str]:
    names = [f"{_rand_ident(rng)}{i}" for i in range(n_funcs)]
    old = "".join(f"def {n}(a):\n    return a\n\n\n" for n in names)
    changed = set(rng.sample(names, rng.randint(1, len(names))))
    new = "".join(
        f"def {n}(a{', b' if n in changed else ''}):\n    return a\n\n\n" for n in names
    )
    return old, new


def _reg_diff_quoted_path(rng: random.Random, _workdir: Path) -> RegressionCheck:
    """Session bug: git-quoted paths were silently dropped.  Oracle: the
    quoted diff parses to the same content, keyed by the decoded path."""
    stem = "".join(
        rng.choice(_NAME_CHARS + "".join(_PATH_SPECIALS))
        for _ in range(rng.randint(3, 10))
    )
    path = f"pkg{rng.choice(_PATH_SPECIALS)}dir/m{stem}.py"
    old, new = _rand_changed_python(rng, rng.randint(1, 3))
    quoted = _make_diff(_git_quote(f"a/{path}"), _git_quote(f"b/{path}"), old, new)
    if rng.random() < 0.5:  # timestamps after the name, as `diff -u` emits
        quoted = quoted.replace('"\n', '"\t2024-01-01 00:00:00\n', 2)

    def check() -> str | None:
        from impactguard.pipeline import _parse_unified_diff

        got = _parse_unified_diff(quoted)
        if list(got) != [path]:
            return f"quoted path {path!r} parsed as {list(got)!r}"
        old_text, new_text = got[path]
        if "b):" not in new_text:
            return f"changed lines lost for {path!r}"
        return None

    return check


def _reg_diff_repeated_file(rng: random.Random, _workdir: Path) -> RegressionCheck:
    """Session bug: a file appearing twice in a diff overwrote its first
    section.  Oracle: every +/- line of every section survives."""
    name = f"m{_rand_ident(rng)}.py"
    sections = []
    for _ in range(rng.randint(2, 4)):
        old, new = _rand_changed_python(rng, rng.randint(1, 3))
        sections.append(_make_diff(f"a/{name}", f"b/{name}", old, new))
    text = "".join(sections)

    def check() -> str | None:
        from impactguard.pipeline import _parse_unified_diff

        old_text, new_text = _parse_unified_diff(text).get(name, ("", ""))
        for line in text.splitlines():
            if line.startswith(("---", "+++", "@@")):
                continue
            if line.startswith("-") and line[1:] not in old_text.split("\n"):
                return f"removed line lost: {line!r}"
            if line.startswith("+") and line[1:] not in new_text.split("\n"):
                return f"added line lost: {line!r}"
        return None

    return check


def _reg_diff_dash_lines(rng: random.Random, _workdir: Path) -> RegressionCheck:
    """Existing regression (test_diff_removed_line_starting_with_dashes):
    content lines beginning ``--``/``++`` inside a hunk are not headers.
    Oracle: no phantom files, and the content is kept verbatim."""
    lang_ext = rng.choice([".hs", ".py"])
    name = f"m{_rand_ident(rng)}{lang_ext}"
    marker = rng.choice(
        ["-- note", "-- impactguard: ignore", "--- x", "-- a/evil.py", "++ b/evil.py"]
    )
    old = f"{marker}\nfoo x = x\n" if lang_ext == ".hs" else f"x = 1\n{marker}\ny = 2\n"
    new = old.replace(
        marker, rng.choice(["-- other", "++ z", "+++ b/z.py", "--- a/z.py"]), 1
    )
    text = _make_diff(f"a/{name}", f"b/{name}", old, new, context=rng.randint(0, 3))

    def check() -> str | None:
        from impactguard.pipeline import _parse_unified_diff

        got = _parse_unified_diff(text)
        if list(got) != [name]:
            return f"phantom/missing files: {list(got)!r}"
        if marker not in got[name][0].split("\n"):
            return f"dash-prefixed content line lost: {marker!r}"
        return None

    return check


def _reg_adversarial_noise(
    rng: random.Random, _workdir: Path
) -> RegressionCheck | None:
    """Existing regressions (tests/adversarial_generator.py): camouflaged
    breaking changes.  Mutation: surround them with harmless noise --
    unrelated identical functions, shuffled order, duplicates and malformed
    junk entries.  Oracle: the disguised break is still detected."""
    gen = _adversarial_generator()
    if gen is None:
        return None
    pair = gen.generate(rng.choice(gen.list_strategies()), seed=rng.randrange(2**32))
    old, new = copy.deepcopy(pair.old_signatures), copy.deepcopy(pair.new_signatures)
    for _ in range(rng.randint(0, 20)):  # unrelated, unchanged functions
        name = _rand_ident(rng, "noise_")
        sig = {
            "fqname": f"noise.py:{name}",
            "name": name,
            "positional": [
                {
                    "name": "a",
                    "has_default": False,
                    "type": rng.choice([None, "int", "str | None"]),
                }
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
            "decorators": [],
        }
        old.append(copy.deepcopy(sig))
        new.append(copy.deepcopy(sig))
    for side in (old, new):
        for _ in range(rng.randint(0, 3)):  # malformed junk the loader must skip
            side.append(copy.deepcopy(rng.choice(INTERESTING_VALUES)))
            side.append(
                {
                    "fqname": f"junk.py:{_rand_ident(rng)}",
                    "positional": rng.choice([None, 1.5, "x"]),
                }
            )
        if side and rng.random() < 0.3:  # exact duplicate of a real entry
            side.append(
                copy.deepcopy(
                    rng.choice([s for s in side if isinstance(s, dict)] or [{}])
                )
            )
        rng.shuffle(side)

    def check() -> str | None:
        from impactguard.compare_signatures import compare

        ok, failures = pair.verify(compare(old, new, include_private=True))
        return None if ok else f"{pair.strategy_name}: {failures}"

    return check


def _adversarial_generator() -> Any:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from tests import adversarial_generator
    except ImportError:
        return None
    return adversarial_generator


def _reg_malformed_neighbour(
    rng: random.Random, _workdir: Path
) -> RegressionCheck | None:
    """Session bug: one malformed entry crashed compare().  Oracle: a real
    breaking change is still reported next to a malformed sibling."""
    gen = _adversarial_generator()
    if gen is None:
        return None
    pair = gen.generate(rng.choice(gen.list_strategies()), seed=rng.randrange(2**32))
    old, new = copy.deepcopy(pair.old_signatures), copy.deepcopy(pair.new_signatures)
    bad_fields = list(SIGNATURE_MUTATIONS.values())
    target = rng.choice([old, new])
    victim = {
        "fqname": f"other.py:{_rand_ident(rng)}",
        "name": "x",
        "positional": [],
        "kwonly": [],
        "vararg": False,
        "kwarg": False,
    }
    rng.choice(bad_fields)(victim)
    target.insert(rng.randint(0, len(target)), victim)

    def check() -> str | None:
        from impactguard.compare_signatures import compare

        ok, failures = pair.verify(compare(old, new, include_private=True))
        return (
            None if ok else f"{pair.strategy_name} next to {victim!r:.80}: {failures}"
        )

    return check


def _reg_union_reorder(rng: random.Random, _workdir: Path) -> RegressionCheck:
    """Existing regression (test_reordered_union_is_not_a_type_change).
    Oracle: permuting union members (incl. nested generics, Optional) is not
    reported as any kind of change."""
    pool = [
        "int",
        "str",
        "None",
        "bytes",
        "float",
        "list[int]",
        "dict[str, int]",
        "tuple[int, str]",
        "Callable[[int], str]",
        "Path",
    ]
    members = rng.sample(pool, rng.randint(2, 5))
    shuffled = members[:]
    while shuffled == members:
        rng.shuffle(shuffled)
    style = rng.choice(["pipe", "Union"])

    def fmt(ms: list[str]) -> str:
        return " | ".join(ms) if style == "pipe" else f"Union[{', '.join(ms)}]"

    def sig(t: str) -> dict[str, Any]:
        return {
            "fqname": "m.py:f",
            "name": "f",
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
            "positional": [{"name": "a", "has_default": False, "type": t}],
            "return_type": t,
        }

    def check() -> str | None:
        from impactguard.compare_signatures import compare

        result = compare(
            [sig(fmt(members))], [sig(fmt(shuffled))], include_private=True
        )
        if result["breaking"] or result["nonbreaking"]:
            return f"{fmt(members)} -> {fmt(shuffled)} reported {result['breaking'] + result['nonbreaking']}"
        return None

    return check


def _reg_ignore_added_in_new(rng: random.Random, _workdir: Path) -> RegressionCheck:
    """Existing regression (test_ignore_comment_added_in_new_version...).
    Oracle: any breaking change on a function ignored in the new version is
    suppressed, while an un-ignored sibling's break is still reported."""

    def sig(name: str, n_args: int, ignored: bool) -> dict[str, Any]:
        return {
            "fqname": f"m.py:{name}",
            "name": name,
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
            "positional": [
                {"name": f"a{i}", "has_default": False} for i in range(n_args)
            ],
            "ignored": ignored,
        }

    hidden, visible = _rand_ident(rng, "h"), _rand_ident(rng, "v")
    n = rng.randint(1, 4)
    old = [sig(hidden, n, False), sig(visible, n, False)]
    new = [sig(hidden, n + rng.randint(1, 3), True), sig(visible, n + 1, False)]

    def check() -> str | None:
        from impactguard.compare_signatures import compare

        result = compare(old, new, include_private=True)
        if any(f"m.py:{hidden}" in b for b in result["breaking"]):
            return f"ignored function still reported: {result['breaking']}"
        if f"m.py:{hidden}" not in result["suppressed"]:
            return "ignored function missing from 'suppressed'"
        if not any(f"m.py:{visible}" in b for b in result["breaking"]):
            return "un-ignored sibling's break was hidden"
        return None

    return check


def _reg_cache_roundtrip(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Existing regression (test_cached_ast_keeps_line_numbers_across_cache_hit).
    Oracle: re-extracting through the AST cache gives identical signatures
    (line numbers included)."""
    names = [f"{_rand_ident(rng)}{i}" for i in range(rng.randint(2, 6))]
    blank = "\n" * rng.randint(0, 5)
    src = blank.join(f"def {n}(a, b={i}):\n    return a\n" for i, n in enumerate(names))
    path = workdir / f"cache_{_rand_ident(rng)}.py"

    def check() -> str | None:
        from impactguard.extract_signatures import extract

        path.write_text(src)
        first = extract([str(path)])
        second = extract([str(path)])  # served from the AST cache
        return (
            None
            if first == second
            else f"cache hit changed signatures: {first} != {second}"
        )

    return check


REGRESSION_MUTATORS: dict[
    str, Callable[[random.Random, Path], RegressionCheck | None]
] = {
    # bugs found and fixed in this hardening pass
    "ignore_separator": _reg_ignore_separator,
    "long_chain": _reg_long_chain,
    "chained_callee": _reg_chained_callee,
    "python_parser_overflow": _reg_python_parser_overflow,
    "group_isolation": _reg_group_isolation,
    "diff_quoted_path": _reg_diff_quoted_path,
    "diff_repeated_file": _reg_diff_repeated_file,
    "malformed_neighbour": _reg_malformed_neighbour,
    # pre-existing regression tests / adversarial generator
    "diff_dash_lines": _reg_diff_dash_lines,
    "adversarial_noise": _reg_adversarial_noise,
    "union_reorder": _reg_union_reorder,
    "ignore_added_in_new": _reg_ignore_added_in_new,
    "cache_roundtrip": _reg_cache_roundtrip,
}


def _run_regression(name: str, case_seed: int, workdir: Path) -> str | None:
    check = REGRESSION_MUTATORS[name](random.Random(case_seed), workdir)
    return None if check is None else check()


def fuzz_mutate(workdir: Path, opts: argparse.Namespace) -> list[Failure]:
    from impactguard.extract_signatures import extract
    from impactguard.languages.lib.registry import get_extractor_by_language

    rng = random.Random(opts.seed)
    crash_dir = Path(opts.crash_dir)
    source_seeds = _load_source_seeds()
    langs = sorted(lang for lang, corpus in source_seeds.items() if corpus)
    all_seed_texts = [t for corpus in source_seeds.values() for t in corpus]

    # Diff seeds: real unified diffs between a seed and a mutated copy of it.
    diff_seeds: list[str] = [text for text, _ in DIFF_CASES.values()]
    for lang in langs:
        extractor = get_extractor_by_language(lang)
        assert extractor is not None
        text = source_seeds[lang][0]
        changed = _mutate_text(rng, text, [])
        name = f"pkg/mod{extractor.extensions[0]}"
        diff_seeds.append(
            "".join(
                difflib.unified_diff(
                    text.splitlines(keepends=True),
                    changed.splitlines(keepends=True),
                    fromfile=f"a/{name}",
                    tofile=f"b/{name}",
                )
            )
        )

    # Signature-JSON seed: real extraction output.
    py_seed = workdir / "seed.py"
    py_seed.write_text(SAMPLE_PY + "".join(source_seeds.get("python", [])[:3]))
    sig_seed = extract([str(py_seed)])

    seen: dict[str, Failure] = {}
    kinds = [k for k in opts.kinds.split(",") if k]
    weights = {"extract": 6, "diff": 2, "compare": 2, "regress": 4}
    unknown_kinds = set(kinds) - set(weights)
    if unknown_kinds:
        raise SystemExit(f"unknown --kinds: {', '.join(sorted(unknown_kinds))}")
    counts = dict.fromkeys(kinds, 0)
    regress_counts: dict[str, int] = {}
    deadline = time.monotonic() + opts.time_budget if opts.time_budget else None

    for i in range(opts.iterations):
        if deadline is not None and time.monotonic() > deadline:
            break
        kind = rng.choices(kinds, weights=[weights[k] for k in kinds])[0]
        counts[kind] += 1
        if kind == "regress":
            reg_name = rng.choice(sorted(REGRESSION_MUTATORS))
            case_seed = rng.randrange(2**32)
            regress_counts[reg_name] = regress_counts.get(reg_name, 0) + 1
            data = json.dumps({"mutator": reg_name, "case_seed": case_seed}).encode()
            target, ext = f"regress-{reg_name}", ".json"
            run = functools.partial(_run_regression, reg_name, case_seed, workdir)
        elif kind == "extract":
            lang = rng.choice(langs)
            extractor = get_extractor_by_language(lang)
            assert extractor is not None
            ext = extractor.extensions[0]
            data = _mutate_source(rng, rng.choice(source_seeds[lang]), all_seed_texts)
            target, path = f"extract-{lang}", workdir / f"case{ext}"
            path.write_bytes(data)
            run: Callable[[], str | None] = functools.partial(
                _run_extract_target, lang, path
            )
        elif kind == "diff":
            text = _mutate_diff(rng, rng.choice(diff_seeds), all_seed_texts)
            data, target, ext = (
                text.encode("utf-8", errors="surrogatepass"),
                "diff",
                ".diff",
            )
            run = functools.partial(_run_diff_target, text)
        else:
            mutated = sig_seed
            for _ in range(rng.randint(1, 3)):
                mutated = _mutate_json_value(rng, mutated)
            raw = json.dumps(mutated)
            if rng.random() < 0.2:  # also mutate the JSON text itself
                raw = _mutate_text(rng, raw, [])
            data, target, ext = (
                raw.encode("utf-8", errors="surrogatepass"),
                "compare",
                ".json",
            )
            path = workdir / "case.json"
            path.write_bytes(data)
            run = functools.partial(_run_compare_target, path)

        started = time.monotonic()
        try:
            problem = run()
            key = f"{target}:oracle:{problem.split(':')[0][:40]}" if problem else None
        except Exception as exc:  # noqa: BLE001 - every escape is a finding
            problem, key = _err(exc), f"{target}:{_crash_key(exc)}"
        elapsed = time.monotonic() - started
        if problem is None and elapsed > SLOW_SECONDS:
            problem, key = f"slow: {elapsed:.1f}s", f"{target}:slow"
        if problem is None or key in seen:
            continue
        saved = _save_crash(crash_dir, target, ext, data)
        seen[key] = (
            f"mutate {key} (iter {i})",
            f"{problem}\n      replay: python tools/fuzz.py --replay {saved}",
        )

    breakdown = ", ".join(f"{k}={v}" for k, v in counts.items())
    print(f"  ran {sum(counts.values())} cases ({breakdown}) seed={opts.seed}")
    if regress_counts:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(regress_counts.items()))
        print(f"  regression mutators: {detail}")
    return list(seen.values())


def replay(path: Path) -> int:
    """Re-run one saved crash file and show the full traceback."""
    target = path.name.split("__")[0]
    data = path.read_bytes()
    if target.startswith("regress-"):
        case = json.loads(data)
        with tempfile.TemporaryDirectory(prefix="impactguard_replay_") as tmp:
            problem = _run_regression(
                case["mutator"], int(case["case_seed"]), Path(tmp)
            )
    elif target.startswith("extract-"):
        problem = _run_extract_target(target.removeprefix("extract-"), path)
    elif target == "diff":
        problem = _run_diff_target(data.decode("utf-8", errors="surrogatepass"))
    elif target == "compare":
        problem = _run_compare_target(path)
    else:
        print(f"unknown crash target {target!r}")
        return 2
    print(f"oracle violation: {problem}" if problem else "no failure reproduced")
    return 1 if problem else 0


# ── driver ───────────────────────────────────────────────────────────────────

SUITES: dict[str, Callable[[Path, argparse.Namespace], list[Failure]]] = {
    "compare": fuzz_compare,
    "extract": fuzz_extract,
    "diff": fuzz_diff,
    "mutate": fuzz_mutate,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "suites",
        nargs="*",
        default=list(SUITES),
        help=f"suites to run: {', '.join(SUITES)} (default: all)",
    )
    parser.add_argument(
        "--deep", type=int, default=50_000, help="nesting depth for deep payloads"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show library warnings"
    )
    mut = parser.add_argument_group("mutate suite")
    mut.add_argument(
        "--iterations",
        type=int,
        default=2000,
        help="mutation cases to run (default: 2000)",
    )
    mut.add_argument(
        "--seed", type=int, default=None, help="RNG seed (default: random, printed)"
    )
    mut.add_argument(
        "--time-budget",
        type=float,
        default=0,
        help="stop mutating after N seconds (0 = no limit)",
    )
    mut.add_argument(
        "--crash-dir", default="fuzz-crashes", help="where crashing inputs are saved"
    )
    mut.add_argument(
        "--kinds",
        default="extract,diff,compare,regress",
        help="comma-separated mutation families (default: all); 'regress' "
        "replays past bugs as targeted mutators with metamorphic oracles",
    )
    mut.add_argument(
        "--replay",
        type=Path,
        metavar="FILE",
        help="re-run one saved crash file and exit",
    )
    args = parser.parse_args(argv)
    if args.seed is None:
        args.seed = random.SystemRandom().randrange(2**32)
    if args.replay is not None:
        return replay(args.replay)
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
            fails = SUITES[name](workdir, args)
            print(
                f"[{name}] {len(fails)} failure(s) in {time.monotonic() - started:.1f}s"
            )
            for label, detail in fails:
                print(f"  {label}: {detail}")
            total.extend(fails)
    print(f"TOTAL: {len(total)} failure(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
