## Failure Mode Analysis: ImpactGuard

### Summary
ImpactGuard is a deterministic API impact analyzer that extracts signatures, compares old/new API surfaces, traces call sites, and assigns risk scores. Its primary risk surface is **silent correctness failure** — producing a LOW/MEDIUM/HIGH/UNKNOWN classification that downstream consumers (CI gates, human reviewers) treat as authoritative, while the underlying analysis may be incomplete, stale, or confounded by fundamental static-analysis limitations.

---

### High Priority Failures (score ≥ 8)

**1. UNKNOWN classification passes gate by default**
- **Category:** Silent failure / Assumption violation
- **Likelihood:** 3-High | **Impact:** 4-Critical | **Detectability:** 3-Silent
- **Priority:** 10
- **Mechanism:** Without runtime tracing, every change is classified UNKNOWN. If `block_unknown` is `false` (default), the gate silently passes with no signal. A CI pipeline that "always passes" gives false confidence.
- **Mitigation:** Change default `block_unknown` to `true`, or require explicit opt-out. Add a CI-time warning when 0 runtime observations were provided.

**2. Dynamic dispatch is invisible to static analysis**
- **Category:** Code / Algorithm limitation
- **Likelihood:** 3-High | **Impact:** 3-High | **Detectability:** 3-Silent
- **Priority:** 9
- **Mechanism:** Calls through decorators, `getattr`, `__call__`, `functools.partial`, `__init_subclass__`, and higher-order functions leave no trace in the call graph. A breaking change to a dynamically-dispatched function will show 0 call sites and 0 impact — the report says "no risk" while production breaks.
- **Mitigation:** Document this blind spot prominently in the HTML report and CLI output. Consider a `--conservative` mode that flags functions with no call-site coverage as UNKNOWN (requiring manual review).

**3. FQN collision in monorepo with same-named files**
- **Category:** Assumption violation
- **Likelihood:** 3-High | **Impact:** 3-High | **Detectability:** 2-Hard
- **Priority:** 9
- **Mechanism:** FQNs use file basenames (e.g., `utils.py:parse`). Two `utils.py` files in different subdirectories produce colliding FQNs. Pipeline detects this and warns, but does not resolve — collision silently merges signatures, producing incorrect `REMOVED`/`ADDED` detections when either file changes.
- **Mitigation:** Default to relative-path-based FQNs (e.g., `src/parser/utils.py:parse`). The `base_path` config already exists for this. Either require it or auto-detect from `impactguard.toml` location.

**4. Stale call graph produces stale results**
- **Category:** Dependency failure / Silent failure
- **Likelihood:** 3-High | **Impact:** 3-High | **Detectability:** 2-Hard
- **Priority:** 9
- **Mechanism:** The SQLite-backed call graph is only refreshed on explicit `--use-call-graph` runs. If files are modified between runs (common in CI where the graph was built from branch A but checked against branch B), edges reference nodes whose mtime is stale but whose signatures may have changed. The caller/callee queries return incomplete or wrong results.
- **Mitigation:** Always run `sync()` before any query in the pipeline, not only on the `--use-call-graph` path. Add a `max_staleness_seconds` config and warn/abort if exceeded.

**5. Exposure normalization is scan-local**
- **Category:** Semantic mismatch between metric and reality
- **Likelihood:** 3-High | **Impact:** 2-Medium | **Detectability:** 3-Silent
- **Priority:** 8
- **Mechanism:** `exposure()` normalizes call count against `max_count` within the current scan: `log(1+count) / log(1+max_count)`. The hottest function in the scan always scores 1.0. Across scans (or CI runs), exposure scores are incomparable. A function called 2x in a small scan could score the same 1.0 as one called 1e6x in a large scan.
- **Mitigation:** Default `exposure_max_count` to a configurable absolute value (e.g., 1000). Document that relative normalization is for ranking within a single run, not absolute risk.

---

### Medium Priority Failures (score 5–7)

**6. Config poisoning from shared parent directories** — Likelihood 2 | Impact 3 | Detectability 2 | Score 7
`_find_config_file` walks up from CWD stopping at `.git`. In a shared filesystem (CI workspace, monorepo), a sibling or parent project's `impactguard.toml` could be picked up. Mitigation: require `--config` or validate the config file path belongs to the project root.

**7. Post-commit hook runs full scan (not incremental)** — Likelihood 3 | Impact 2 | Detectability 2 | Score 7
Re-scans all tracked files on every commit. On a 500K-line codebase this is slow, leading developers to disable the hook. Mitigation: implement incremental scanning using the call graph's staleness detection.

**8. Regex fallback silently loses signatures** — Likelihood 2 | Impact 3 | Detectability 2 | Score 7
When tree-sitter packages are absent, regex extraction is "best-effort" with no signal indicating what was missed. A signature with a complex type annotation or decorator could be silently dropped, making a breaking change invisible. Mitigation: log a warning per-file when regex fallback activates, and how many signatures were extracted vs estimated.

**9. Call graph edge targets may not resolve to node FQNs** — Likelihood 2 | Impact 3 | Detectability 2 | Score 7
Cross-file call target resolution depends on file_imports being populated before calls are indexed. The 3-pass build fixes this, but direct API callers using `_index_file` + `_index_calls` out of order will produce edges pointing to unresolvable targets that BFS queries silently skip. Mitigation: validate edge targets in `stats()` or a `--validate` flag; log a warning for dangling edges.

**10. Feedback loop is a no-op until ≥5 outcomes per category** — Likelihood 2 | Impact 2 | Detectability 3 | Score 7
The calibration system does nothing until 5 acceptance/rejection outcomes accumulate per weight category. Teams that adopt impactguard for small projects may never reach this threshold. The feature appears operational but is inert. Mitigation: seed with sensible defaults from a meta-analysis of similar projects; log a message showing how many more data points are needed.

**11. Type annotation changes undetectable without annotations** — Likelihood 3 | Impact 2 | Detectability 2 | Score 7 (MITIGATED)
`TYPE_CHANGED` detection requires type annotations in both old and new signatures. Many Python codebases have partial or no annotations. A function that adds a type annotation to an unannotated parameter does not trigger `TYPE_CHANGED`. Mitigation: `_NAME_TYPE_HINTS` (60+ common parameter names) and `_infer_possible_type()` infer a likely type from parameter name when one side is missing. Covers `is_`/`has_`/`should_` prefix (→ `bool`) and `_id`/`_ids` suffix (→ `int`). Unknown names are left unannotated.

**12. Python-only runtime tracing and CST patching** — Likelihood 2 | Impact 3 | Detectability 2 | Score 7 (MITIGATED)
`trace_calls_prod.py` (Python decorator) and `cst_patch.py` (libcst) work only for Python. For the 13 other languages, runtime data must be supplied externally in a JSON schema that may not match. Broken patches or mismatched runtime data produce no error. Mitigation: `validate_runtime()` is now called inside `load_runtime_observations()` — invalid JSON is logged and gracefully degrades to an empty list. `trace_calls_prod.py` and `cst_patch.py` both carry Python-only docstring notices. `fix_generation.py` skips CST patches for non-`.py` files and falls back to text patches.

---

### Low Priority Failures (score ≤ 4)

**13. SQLite WAL contention from concurrent sync() calls** — Score 4 (MITIGATED)
The single `sqlite3.Connection` is not thread-safe — concurrent `sync()`/`build()` calls from multiple threads can corrupt the connection. Mitigation: `check_same_thread=False` + `timeout=5` in `sqlite3.connect()`, `PRAGMA busy_timeout=5000`, and a `threading.Lock` (`_write_lock`) serializing all write operations (`build()`, `sync()`, `remove_stale()`, `clear()`, `close()`). Read queries (BFS, stats, call sites) remain lock-free under WAL.

**14. Signature hash collision (sha256, negligible risk)** — Score 4
**15. Pre-commit hook removes `SKIP_SIGNATURE_HOOK` env** — Score 4
**16. TOCTOU between file stat and read in `_is_stale`** — Score 3
**17. `git diff` parsing misses binary file changes** — Score 3
**18. `impactguard ignore` comment parsing fails on unusual syntax** — Score 3
**19. KPI dashboard aggregation wrong if timestamps cross DST boundary** — Score 2

---

### Key Mitigations

1. **Change `block_unknown` default to `true`** — The single highest-impact change. UNKNOWN should mean "requires human review" not "silently pass."
2. **Auto-detect `base_path` from `impactguard.toml` location** — Eliminates FQN collisions and the silent merging bug.
3. **Add `--validate` CLI subcommand** — Runs integrity checks: dangling edges, missing call graph nodes, stale DB, FQN collisions. Human-readable output.
4. **Log per-file extractor mode used** — Tree-sitter vs regex vs AST; number of signatures found. Surface in HTML report as a reliability note.
5. **Always sync call graph before query** — Remove the gap where the DB is used without being refreshed. Add staleness warnings.

### Assumptions Made

- Threat model: opportunistic external attacker (no nation-state), accidental misuse by authorized users
- Analysis performed on the code at `master` HEAD as of June 2026
- The codebase's own CI and dogfooding practices have already caught common failure modes
- External dependencies (tree-sitter, libcst, z3) are assumed correct — their failure modes are not analyzed here
- The failure-mode surface of the 14 language extractors is not analyzed individually (only the common patterns)
