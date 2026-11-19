"""Generic byte/text/structure mutators, seed corpus and oracles."""

from __future__ import annotations

import copy
import hashlib
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .corpus import REPO, require_extractor

if TYPE_CHECKING:
    import random

# ── mutate: seeded mutation-based fuzzing ────────────────────────────────────
#
# Start from *valid* inputs (example sources, diffs built from them, extracted
# signature JSON), apply random byte/text/structure mutations and check
# oracles.  Unlike the fixed payload suites above this explores the space
# around realistic input, so it finds bugs nobody thought to write a case for.
# Runs are deterministic for a given ``--seed``; crashing inputs are written to
# ``--crash-dir`` and can be re-run with ``--replay``.


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


def _op_insert(
    rng: random.Random, text: str, _seeds: list[str], _n: int, pos: int
) -> str | None:
    """Insert an interesting token."""
    return text[:pos] + rng.choice(INTERESTING_TEXT) + text[pos:]


def _op_delete(
    rng: random.Random, text: str, _seeds: list[str], n: int, _pos: int
) -> str | None:
    """Delete a random span."""
    if not n:
        return None
    a, b = _rand_span(rng, n)
    return text[:a] + text[b:]


def _op_duplicate_span(
    rng: random.Random, text: str, _seeds: list[str], n: int, _pos: int
) -> str | None:
    """Repeat a random span a few times."""
    if not n:
        return None
    a, b = _rand_span(rng, n)
    return text[:b] + text[a:b] * rng.randint(1, 8) + text[b:]


def _op_bracket_run(
    rng: random.Random, text: str, _seeds: list[str], _n: int, pos: int
) -> str | None:
    """Insert a run of brackets or operators (deep nesting / long chains)."""
    tok = rng.choice(["(", "[", "{", "<", "(" * 2 + ")", " + 1", ".a()", "-"])
    return text[:pos] + tok * rng.randint(2, 400) + text[pos:]


def _op_truncate(
    _rng: random.Random, text: str, _seeds: list[str], _n: int, pos: int
) -> str | None:
    """Cut the text off at a random position."""
    return text[:pos]


def _op_swap_lines(
    rng: random.Random, text: str, _seeds: list[str], _n: int, _pos: int
) -> str | None:
    """Swap two random lines."""
    lines = text.split("\n")
    if len(lines) > 1:
        i, j = rng.randrange(len(lines)), rng.randrange(len(lines))
        lines[i], lines[j] = lines[j], lines[i]
    return "\n".join(lines)


def _op_repeat_line(
    rng: random.Random, text: str, _seeds: list[str], _n: int, _pos: int
) -> str | None:
    """Duplicate one line many times."""
    lines = text.split("\n")
    if lines:
        i = rng.randrange(len(lines))
        lines[i:i] = [lines[i]] * rng.randint(1, 200)
    return "\n".join(lines)


def _op_splice(
    rng: random.Random, text: str, seeds: list[str], _n: int, pos: int
) -> str | None:
    """Splice the tail of another seed onto this one."""
    if not seeds:
        return None
    other = rng.choice(seeds)
    return text[:pos] + other[rng.randint(0, len(other)) :]


def _op_codepoint(
    rng: random.Random, text: str, _seeds: list[str], n: int, pos: int
) -> str | None:
    """Replace one character with a random code point."""
    if not n:
        return None
    cp = rng.choice(
        [
            rng.randint(0, 0x7F),
            rng.randint(0x80, 0xFFFF),
            rng.randint(0x10000, 0x10FFFF),
        ]
    )
    ch = chr(cp) if not 0xD800 <= cp <= 0xDFFF else "?"
    return text[: pos % n] + ch + text[pos % n + 1 :]


def _op_line_endings(
    rng: random.Random, text: str, _seeds: list[str], _n: int, _pos: int
) -> str | None:
    """Swap line endings for CRLF, CR, form feeds or U+2028."""
    return text.replace("\n", rng.choice(["\r\n", "\r", "\n\f", " "]))


def _op_strip_whitespace(
    rng: random.Random, text: str, _seeds: list[str], _n: int, _pos: int
) -> str | None:
    """Remove indentation / whitespace."""
    return text.replace(rng.choice(["    ", "\t", " "]), "", rng.randint(1, 50))


def _op_clobber(
    rng: random.Random, text: str, _seeds: list[str], _n: int, pos: int
) -> str:
    """Insert an identifier or number (also the fallback for inapplicable ops)."""
    return (
        text[:pos]
        + rng.choice(["0", "9" * 40, "_", "a" * 300, "self", "None"])
        + text[pos:]
    )


_TEXT_OPS = [
    _op_insert,
    _op_delete,
    _op_duplicate_span,
    _op_bracket_run,
    _op_truncate,
    _op_swap_lines,
    _op_repeat_line,
    _op_splice,
    _op_codepoint,
    _op_line_endings,
    _op_strip_whitespace,
    _op_clobber,
]


def _mutate_text(rng: random.Random, text: str, seeds: list[str]) -> str:
    """Apply one random text-level mutation."""
    n = len(text)
    op = _TEXT_OPS[rng.randrange(len(_TEXT_OPS))]
    pos = rng.randint(0, n)
    result = op(rng, text, seeds, n, pos)
    return result if result is not None else _op_clobber(rng, text, seeds, n, pos)


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

    extractor = require_extractor(lang)
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
