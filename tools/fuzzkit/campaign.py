"""The seeded ``mutate`` campaign driver and crash replay."""

from __future__ import annotations

import difflib
import functools
import json
import random
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .corpus import (
    DIFF_CASES,
    SAMPLE_PY,
    SLOW_SECONDS,
    Failure,
    _err,
    require_extractor,
)
from .mutators import (
    _crash_key,
    _load_source_seeds,
    _mutate_diff,
    _mutate_json_value,
    _mutate_source,
    _mutate_text,
    _run_compare_target,
    _run_diff_target,
    _run_extract_target,
    _save_crash,
)
from .regress import REGRESSION_MUTATORS, _run_regression

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable


KIND_WEIGHTS = {"extract": 6, "diff": 2, "compare": 2, "regress": 4}


@dataclass
class _Case:
    """One generated input: bytes to save on failure and a check to run."""

    data: bytes
    target: str
    ext: str
    run: Callable[[], str | None]


class _Campaign:
    """Seed corpus plus case builders for one seeded ``mutate`` run."""

    def __init__(self, rng: random.Random, workdir: Path) -> None:
        from impactguard.extract_signatures import extract

        self.rng = rng
        self.workdir = workdir
        self.source_seeds = _load_source_seeds()
        self.langs = sorted(
            lang for lang, corpus in self.source_seeds.items() if corpus
        )
        self.all_seed_texts = [
            t for corpus in self.source_seeds.values() for t in corpus
        ]
        self.diff_seeds = self._diff_seeds()
        # Signature-JSON seed: real extraction output.
        py_seed = workdir / "seed.py"
        py_seed.write_text(SAMPLE_PY + "".join(self.source_seeds.get("python", [])[:3]))
        self.sig_seed = extract([str(py_seed)])
        self.regress_counts: dict[str, int] = {}

    def _diff_seeds(self) -> list[str]:
        """Return real unified diffs between each seed and a mutated copy."""
        seeds: list[str] = [text for text, _ in DIFF_CASES.values()]
        for lang in self.langs:
            extractor = require_extractor(lang)
            text = self.source_seeds[lang][0]
            changed = _mutate_text(self.rng, text, [])
            name = f"pkg/mod{extractor.extensions[0]}"
            seeds.append(
                "".join(
                    difflib.unified_diff(
                        text.splitlines(keepends=True),
                        changed.splitlines(keepends=True),
                        fromfile=f"a/{name}",
                        tofile=f"b/{name}",
                    )
                )
            )
        return seeds

    def build(self, kind: str) -> _Case:
        """Build one case of the given mutation family."""
        return {
            "regress": self._regress_case,
            "extract": self._extract_case,
            "diff": self._diff_case,
            "compare": self._compare_case,
        }[kind]()

    def _regress_case(self) -> _Case:
        name = self.rng.choice(sorted(REGRESSION_MUTATORS))
        case_seed = self.rng.randrange(2**32)
        self.regress_counts[name] = self.regress_counts.get(name, 0) + 1
        data = json.dumps({"mutator": name, "case_seed": case_seed}).encode()
        run = functools.partial(_run_regression, name, case_seed, self.workdir)
        return _Case(data, f"regress-{name}", ".json", run)

    def _extract_case(self) -> _Case:
        lang = self.rng.choice(self.langs)
        ext = require_extractor(lang).extensions[0]
        data = _mutate_source(
            self.rng, self.rng.choice(self.source_seeds[lang]), self.all_seed_texts
        )
        path = self.workdir / f"case{ext}"
        path.write_bytes(data)
        return _Case(
            data,
            f"extract-{lang}",
            ext,
            functools.partial(_run_extract_target, lang, path),
        )

    def _diff_case(self) -> _Case:
        text = _mutate_diff(
            self.rng, self.rng.choice(self.diff_seeds), self.all_seed_texts
        )
        data = text.encode("utf-8", errors="surrogatepass")
        return _Case(data, "diff", ".diff", functools.partial(_run_diff_target, text))

    def _compare_case(self) -> _Case:
        mutated = self.sig_seed
        for _ in range(self.rng.randint(1, 3)):
            mutated = _mutate_json_value(self.rng, mutated)
        raw = json.dumps(mutated)
        if self.rng.random() < 0.2:  # also mutate the JSON text itself
            raw = _mutate_text(self.rng, raw, [])
        data = raw.encode("utf-8", errors="surrogatepass")
        path = self.workdir / "case.json"
        path.write_bytes(data)
        return _Case(
            data, "compare", ".json", functools.partial(_run_compare_target, path)
        )


def _execute(case: _Case) -> tuple[str | None, str | None]:
    """Run *case*; return ``(problem, dedupe_key)`` or ``(None, None)``."""
    started = time.monotonic()
    try:
        problem = case.run()
        key = f"{case.target}:oracle:{problem.split(':')[0][:40]}" if problem else None
    except Exception as exc:  # noqa: BLE001 - every escape is a finding
        problem, key = _err(exc), f"{case.target}:{_crash_key(exc)}"
    elapsed = time.monotonic() - started
    if problem is None and elapsed > SLOW_SECONDS:
        problem, key = f"slow: {elapsed:.1f}s", f"{case.target}:slow"
    return problem, key


def _parse_kinds(spec: str) -> list[str]:
    kinds = [k for k in spec.split(",") if k]
    unknown = set(kinds) - set(KIND_WEIGHTS)
    if unknown:
        raise SystemExit(f"unknown --kinds: {', '.join(sorted(unknown))}")
    return kinds


def fuzz_mutate(workdir: Path, opts: argparse.Namespace) -> list[Failure]:
    """Run a seeded mutation campaign and return deduplicated failures."""
    # Seeded PRNG on purpose: runs must be reproducible from --seed; nothing
    # here is security-sensitive.
    rng = random.Random(opts.seed)  # nosec B311
    campaign = _Campaign(rng, workdir)
    kinds = _parse_kinds(opts.kinds)
    weights = [KIND_WEIGHTS[k] for k in kinds]
    counts = dict.fromkeys(kinds, 0)
    seen: dict[str, Failure] = {}
    deadline = time.monotonic() + opts.time_budget if opts.time_budget else None

    for i in range(opts.iterations):
        if deadline is not None and time.monotonic() > deadline:
            break
        kind = rng.choices(kinds, weights=weights)[0]
        counts[kind] += 1
        case = campaign.build(kind)
        problem, key = _execute(case)
        if problem is None or key is None or key in seen:
            continue
        saved = _save_crash(Path(opts.crash_dir), case.target, case.ext, case.data)
        seen[key] = (
            f"mutate {key} (iter {i})",
            f"{problem}\n      replay: python tools/fuzz.py --replay {saved}",
        )

    breakdown = ", ".join(f"{k}={v}" for k, v in counts.items())
    print(f"  ran {sum(counts.values())} cases ({breakdown}) seed={opts.seed}")
    if campaign.regress_counts:
        detail = ", ".join(
            f"{k}={v}" for k, v in sorted(campaign.regress_counts.items())
        )
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
