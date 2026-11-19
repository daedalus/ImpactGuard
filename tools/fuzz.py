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
import os
import random
import sys
import tempfile
import time
import warnings
from pathlib import Path

# Make the sibling ``fuzzkit`` package importable both when run as a script
# and when this file is loaded by path (e.g. from the test suite).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import TYPE_CHECKING

from fuzzkit.campaign import KIND_WEIGHTS, fuzz_mutate, replay  # noqa: E402
from fuzzkit.fixed import fuzz_compare, fuzz_diff, fuzz_extract  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable

    from fuzzkit.corpus import Failure

# ── driver ───────────────────────────────────────────────────────────────────

SUITES: dict[str, Callable[[Path, argparse.Namespace], list[Failure]]] = {
    "compare": fuzz_compare,
    "extract": fuzz_extract,
    "diff": fuzz_diff,
    "mutate": fuzz_mutate,
}


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
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
    return parser


def _silence_libraries() -> None:
    """Hide library warnings and stderr chatter (unless --verbose)."""
    import logging

    logging.disable(logging.WARNING)
    warnings.simplefilter("ignore")
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115 - silence library chatter


def _run_suites(args: argparse.Namespace) -> list[Failure]:
    """Run each selected suite in its own temp dir and print its failures."""
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
    return total


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit status."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.seed is None:
        args.seed = random.SystemRandom().randrange(2**32)
    if args.replay is not None:
        return replay(args.replay)
    unknown = [s for s in args.suites if s not in SUITES]
    if unknown:
        parser.error(f"unknown suite(s): {', '.join(unknown)}")
    bad_kinds = [k for k in args.kinds.split(",") if k and k not in KIND_WEIGHTS]
    if bad_kinds:  # validate before stderr is silenced below
        parser.error(f"unknown --kinds: {', '.join(bad_kinds)}")
    if not args.verbose:
        _silence_libraries()
    total = _run_suites(args)
    print(f"TOTAL: {len(total)} failure(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
