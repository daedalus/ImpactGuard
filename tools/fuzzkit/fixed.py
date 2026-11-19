"""Fixed-payload suites: ``compare``, ``extract`` and ``diff``."""

from __future__ import annotations

import copy
import time
from typing import TYPE_CHECKING

from .corpus import (
    BAD_JSON_FILES,
    DIFF_CASES,
    SAMPLE_PY,
    SIGNATURE_MUTATIONS,
    SLOW_SECONDS,
    Failure,
    _err,
    _source_payloads,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


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
