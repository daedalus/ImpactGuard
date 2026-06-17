## Project Overview

ImpactGuard is a multi-language API impact analyzer (Python, TypeScript, JS, Java, Kotlin, Go, Rust, Swift, C, C++, C#, Ruby, Haskell, Zig). Extracts signatures via AST/tree-sitter, detects breaking changes, analyzes call-site impact, and assigns risk scores (S×E×C×λ model).

---

## Key Files

| File | Purpose |
|------|---------|
| `src/impactguard/extract_signatures.py` | Python signature extraction (stdlib `ast`) |
| `src/impactguard/languages/*.py` | 14 language extractors (tree-sitter + regex fallback) |
| `src/impactguard/languages/lib/shared.py` | Shared helpers: `has_ignore_comment_fallback`, `has_ignore_comment`, `node_text`, `child_of_type` |
| `src/impactguard/compare_signatures.py` | Semantic diff: breaking/non-breaking/suppressed classification |
| `src/impactguard/impact_analysis.py` | Call-site impact + transitive BFS tracking |
| `src/impactguard/risk_model.py` | S×E×C×λ risk scoring |
| `src/impactguard/kpi.py` | 12-metric KPI dashboard (mean_severity, risk_distribution, etc.) |
| `src/impactguard/feedback.py` | Patch-outcome feedback loop + weight calibration |
| `src/impactguard/pipeline.py` | Pipeline orchestrator (`run_pipeline`, `_parse_unified_diff`) |
| `src/impactguard/call_graph.py` | SQLite-backed call graph with staleness detection |
| `src/impactguard/generate_report.py` | Static HTML + markdown report generation |
| `src/impactguard/__main__.py` | CLI entry point (18+ subcommands) |
| `extract_signatures.py` | Standalone script (toplevel, not under src/) |

---

## CLI Subcommands

```
{extract,compare,analyze,risk,report,report-sarif,enforce,suggest,patch,
 extract-calls,trace,check,check-diff,check-commit,check-commits,
 install-hooks,generate-changelog,baseline,semver,report-markdown,
 feedback,history,kpi,validate-config,behavior}
```

Run `impactguard --help` for details.

---

## Testing

- **Test framework:** pytest
- **Coverage target:** ≥ 80%
- **Command:** `rtk pytest` (uses rtk wrapper)
- **All tests pass:** 3189+ tests

---

## Code Quality

- **Linter:** ruff (0 issues target)
- **Type checker:** mypy (strict mode)

---

## Git Hooks

Two hooks installed via `impactguard install-hooks .`:

1. **Pre-commit** — runs `check-diff --pipe` on staged changes, sets `SKIP_SIGNATURE_HOOK=1` to prevent recursion
2. **Post-commit** — runs `check-commit HEAD` + signature extraction, saves/restores `SKIP_SIGNATURE_HOOK`

Both hooks save and restore the original env value instead of unconditionally popping.

---

## Ignore Comments

All 15 languages support `impactguard: ignore` comments on or immediately before a function definition. Whitespace and case variations handled automatically (regex: `impactguard\s*:\s*ignore`, case-insensitive).

| Comment style | Languages |
|---------------|-----------|
| `# impactguard: ignore` | Python, Ruby |
| `// impactguard: ignore` | TypeScript, JS, Java, Kotlin, Go, Rust, Swift, C, C++, C# |
| `-- impactguard: ignore` | Haskell |
| `// impactguard: ignore` | Zig |

---

## Recent Mitigations (FM #9–#19)

All 19 failure modes from the project audit are MITIGATED:

| # | Issue | Fix |
|---|-------|-----|
| 9 | Dangling call-graph edges | `stats()` validates edge targets resolve to node FQNs |
| 10 | Calibration threshold inertia | Per-category data-need logging, `compute_data_needs()` public function |
| 11 | Type annotation blind spots | `_NAME_TYPE_HINTS` (60+ mappings), `_infer_possible_type()` |
| 12 | Python-only fallback gaps | `validate_runtime()` in load path, non-`.py` CST skip |
| 13 | SQLite WAL contention | `threading.Lock` serializing writes, `busy_timeout=5000` |
| 14 | mtime false negatives | `_is_stale()` also compares file `size` |
| 15 | Pre-commit hook recursion | `SKIP_SIGNATURE_HOOK=1` with env save/restore |
| 16 | TOCTOU file stat/read race | Read content first, derive size from bytes, stat mtime after |
| 17 | Binary files in git diff | `Binary files ... differ` detected, warning logged, excluded |
| 18 | Ignore comment unusual syntax | Regex replaces exact substring match |
| 19 | DST in KPI timestamps | All timestamps use `datetime.now(UTC)`, `computed_at` in dashboard |

---

## Known Architecture

### Diff Parsing (`_parse_unified_diff`)
- Tracks `---`/`+++` lines for file names
- Only includes files with registered extractor (`_get_extractor`) + safe path (`is_safe_path`)
- Binary files logged as warning, excluded from result
- Returns `dict[str, tuple[str, str]]` — old/new content per file

### Call Graph (`CallGraphDB`)
- SQLite-backed with WAL mode
- Write lock (`_write_lock`, `threading.Lock`) serializing `build()`, `sync()`, `remove_stale()`, `clear()`, `close()`
- Reads (BFS, stats) are lock-free
- Staleness: compares `modified_at` + `size` from `stat()`
- TOCTOU resilience: read-first, stat-after pattern

### Language Extractors
- All implement `LanguageExtractor` protocol (`src/impactguard/languages/base.py`)
- Registered via `register()` in `registry.py`
- Third-party extractors via `impactguard.languages` entry point group
- Extractors produce signature dicts with `ignored`, `exported`, `deprecated` flags

---

## Session Bug Prevention Checklist

Before committing any change involving:

### Serialisation / Caching
- [ ] Round-trip test: serialise → deserialise → compare original
- [ ] Verify the serialised format is valid for the deserialiser (e.g. `ast.parse` expects Python source, not `ast.dump` repr)

### Threading / Locking
- [ ] Draw critical section diagram for all threads — verify no lock is acquired twice without RLock (deadlock) and no window exists between check and mutate
- [ ] Verify shared state is inaccessible after `close()`/cleanup (thread-local stale references need a guard flag)
- [ ] Run concurrent stress test (multiple threads + close)

### Connection / Resource Lifecycle
- [ ] Resources released for ALL threads, not just the calling thread
- [ ] `_closed` guard prevents use-after-close
- [ ] `close()` logs errors, never silently swallows

### Code Hygiene
- [ ] `grep -r '<removed_function>' src/` — no dangling references after refactor
- [ ] Tests updated to match new postconditions (raises where it didn't before, different return values)
- [ ] `ruff check` — 0 lint errors

---

## Release Process

```bash
./tools/release.sh          # bump patch (default)
./tools/release.sh minor
./tools/release.sh major
```

Steps: `bumpversion` → `git push` + `git push --tags` → `python -m build` → `gh release create <tag> --generate-notes`
