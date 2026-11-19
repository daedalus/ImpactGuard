"""Regression mutators: past bugs regenerated with random parameters."""

from __future__ import annotations

import copy
import difflib
import random
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .corpus import REPO, SIGNATURE_MUTATIONS, require_extractor
from .mutators import INTERESTING_VALUES

if TYPE_CHECKING:
    from pathlib import Path

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

    extractor = require_extractor(lang)
    return extractor.extract_signatures([str(path)])


def _sig_view(sigs: list[dict[str, Any]]) -> list[tuple[str, int, bool]]:
    return sorted(
        (s["fqname"], s.get("lineno", 0), bool(s.get("ignored"))) for s in sigs
    )


def _reg_ignore_separator(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Exotic line separators inside comments must not move ignore flags.

    Session bug: form feeds / U+2028 shifted lines so ignore comments attached
    to the wrong function. Oracle: inserting an exotic separator *inside a
    comment* must not change (fqname, lineno, ignored).
    """
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

    extractor = require_extractor(lang)
    return extractor.extensions[0]


def _reg_long_chain(rng: random.Random, workdir: Path) -> RegressionCheck:
    """A long expression chain in a function body must not lose signatures.

    Session bug: recursive tree walks overflowed on long expression chains.
    Oracle: adding a function containing an N-term chain yields exactly the old
    signatures plus ``chainfn``.
    """
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
    """Return True when *lang*'s tree-sitter grammar is installed.

    True when *lang*'s tree-sitter grammar is installed (else the extractor
    runs its regex fallback).
    """
    import importlib.util

    module = {"csharp": "tree_sitter_c_sharp"}.get(lang, f"tree_sitter_{lang}")
    try:
        return importlib.util.find_spec("tree_sitter") is not None and (
            importlib.util.find_spec(module) is not None
        )
    except (ImportError, ValueError):
        return False


def _reg_chained_callee(rng: random.Random, workdir: Path) -> RegressionCheck:
    """Chained calls ``g()()()...`` must resolve without overflowing.

    Session bug: ``g()()()...`` overflowed the call-name resolver. Oracle: no
    crash and every resolved call name is ``g``.
    """
    lang = rng.choice(sorted(CHAINED_CALL_FUNCS))
    src = CHAINED_CALL_FUNCS[lang].format(calls="()" * rng.randint(300, 6000))
    path = workdir / f"chained{_ext_for(lang)}"

    def check() -> str | None:

        path.write_text(LANG_TEMPLATES[lang][2] + src)
        extractor = require_extractor(lang)
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
    """Pathological Python nesting must not escape group extraction.

    Session bug: CPython's parser raises MemoryError/RecursionError on
    pathological nesting. Oracle: the pipeline's group extraction and call
    extraction never let an exception escape.
    """
    shape = rng.choice(["-", "not ", "lambda: ", "1 if 1 else ", "+"])
    n = rng.randint(3000, 30000)
    src = "x = " + (" + ".join(["1"] * n) if shape == "+" else shape * n + "1") + "\n"
    path = workdir / "deep_overflow.py"

    def check() -> str | None:
        from impactguard.pipeline import _extract_group

        path.write_text(src)
        extractor = require_extractor("python")
        _extract_group(extractor, [str(path)], None, False, {}, [])
        extractor.extract_calls(path)
        return None

    return check


def _reg_group_isolation(rng: random.Random, workdir: Path) -> RegressionCheck:
    """One pathological file must not drop its language group.

    Session bug: one pathological file discarded every signature of its
    language group. Oracle: all healthy files' signatures survive.
    """
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
        from impactguard.pipeline import _extract_group

        bad.write_text(bad_src + "\n")
        extractor = require_extractor(lang)
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
    """Git-quoted diff paths must parse like their unquoted form.

    Session bug: git-quoted paths were silently dropped. Oracle: the quoted
    diff parses to the same content, keyed by the decoded path.
    """
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
        _, new_text = got[path]
        if "b):" not in new_text:
            return f"changed lines lost for {path!r}"
        return None

    return check


def _reg_diff_repeated_file(rng: random.Random, _workdir: Path) -> RegressionCheck:
    """Every section of a file repeated in a diff must survive.

    Session bug: a file appearing twice in a diff overwrote its first section.
    Oracle: every +/- line of every section survives.
    """
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
    """Hunk lines starting with ``--``/``++`` must not become headers.

    Existing regression (test_diff_removed_line_starting_with_dashes): content
    lines beginning ``--``/``++`` inside a hunk are not headers. Oracle: no
    phantom files, and the content is kept verbatim.
    """
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


def _add_compare_noise(rng: random.Random, old: list[Any], new: list[Any]) -> None:
    """Surround a signature pair with harmless noise, in place.

    Adds unrelated functions identical on both sides, malformed junk the
    loader must skip and exact duplicates, then shuffles both lists.
    """
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


def _reg_adversarial_noise(
    rng: random.Random, _workdir: Path
) -> RegressionCheck | None:
    """Camouflaged breaking changes must survive harmless noise.

    Existing regressions (tests/adversarial_generator.py): camouflaged breaking
    changes. Mutation: surround them with harmless noise -- unrelated identical
    functions, shuffled order, duplicates and malformed junk entries. Oracle:
    the disguised break is still detected.
    """
    gen = _adversarial_generator()
    if gen is None:
        return None
    pair = gen.generate(rng.choice(gen.list_strategies()), seed=rng.randrange(2**32))
    old, new = copy.deepcopy(pair.old_signatures), copy.deepcopy(pair.new_signatures)
    _add_compare_noise(rng, old, new)

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
    """A malformed sibling entry must not hide a real breaking change.

    Session bug: one malformed entry crashed compare(). Oracle: a real breaking
    change is still reported next to a malformed sibling.
    """
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
    """Reordering union members must not count as a type change.

    Existing regression (test_reordered_union_is_not_a_type_change). Oracle:
    permuting union members (incl. nested generics, Optional) is not reported
    as any kind of change.
    """
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
    """An ignore comment added in the new version must suppress.

    Existing regression (test_ignore_comment_added_in_new_version...). Oracle:
    any breaking change on a function ignored in the new version is suppressed,
    while an un-ignored sibling's break is still reported.
    """

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
    """Re-extracting through the AST cache must not change signatures.

    Existing regression (test_cached_ast_keeps_line_numbers_across_cache_hit).
    Oracle: re-extracting through the AST cache gives identical signatures
    (line numbers included).
    """
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
    # Seeded PRNG on purpose: a saved case is replayed from its seed alone.
    rng = random.Random(case_seed)  # nosec B311
    check = REGRESSION_MUTATORS[name](rng, workdir)
    return None if check is None else check()
