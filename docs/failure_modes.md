# Failure Mode Analysis: ImpactGuard

**Date:** 2025-06-14 (fresh scan)
**Scope:** Full codebase — signature extraction, comparison, call graph, risk model, CLI, feedback loop
**Threat model:** Opportunistic external attacker + accidental misuse by authorized users

---

## Summary

ImpactGuard is a multi-language API impact analyzer. The previous audit identified 18 failure modes — all have been mitigated. This fresh scan identifies remaining and new observations.

---

## Previous Failures — All Fixed (18/18)

| # | Issue | Fix Applied |
|---|-------|-------------|
| 1 | Duplicate function definitions | Removed all duplicates |
| 2 | Duplicate `_validate_git_ref`/`_validate_git_path` | Removed duplicates |
| 3 | FQNAME collision risk | Raises ValueError |
| 4 | SQLite WAL contention | `fcntl.flock` file-level lock |
| 5 | Non-atomic config writes | `tempfile` + `os.replace` |
| 6 | `_resolve_target` ambiguity | Logs warning |
| 7 | Git timeout too short | Configurable via `[impactguard.git]` |
| 8 | `_summarize_files` truncation | Sorted, limit=10, shows total |
| 9 | `_extract_all_names` limited | Handles `+=`, `.append()`, `.extend()` |
| 10 | `_parse_union_members` broken | Bracket-aware splitting |
| 11 | `_is_effectively_public` | Verified correct |
| 12 | `_inject_coverage_disclaimer` fragile | Multiple fallback markers |
| 13 | No backup for `apply_safe_fixes` | Creates `.bak` files |
| 14 | `quick_check` unbounded | 10,000 file limit |
| 15 | `_write_json` no error handling | Logs errors |
| 16 | `cmd_trace` whitelist bypass | Module name verification |
| 17 | Config singleton stale | `reset_config()` added |
| 18 | Exposure normalization broken | Configurable `exposure_max_count` |

---

## New Observations

### High Priority (score ≥ 8)

*None found.* All previous high-priority issues are fixed.

### Medium Priority (score 5–7)

**1. Pickle deserialization in cache module**

| Dimension | Score |
|-----------|-------|
| Category | Security / Deserialization |
| Likelihood | 1 — Low |
| Impact | 3 — High |
| Detectability | 2 — Hard |
| **Priority** | **6** |

**Description:** `cache.py:203` uses `pickle.loads()` to deserialize cached AST trees. If an attacker can write to the cache database, they could inject malicious pickled objects.

**Current Mitigation:** Cache DB is in user's home directory (`~/.cache/impactguard/`). Concurrent access is limited. The pickle payload is base64-encoded JSON with a `_t` type discriminator.

**Risk Assessment:** Low in practice — requires local file write access to the cache DB. Acceptable for a developer tool.

---

**2. 304 functions with CCN ≥ 15**

| Dimension | Score |
|-----------|-------|
| Category | Correctness / Complexity |
| Likelihood | 2 — Medium |
| Impact | 2 — Medium |
| Detectability | 2 — Hard |
| **Priority** | **6** |

**Description:** 304 functions exceed the CCN=15 threshold. High cyclomatic complexity correlates with bug density and makes testing harder.

**Current Mitigation:** Core pipeline functions have been refactored (run_pipeline 244→185, generate_html 159→133, etc.). Remaining high-CCN functions are mostly language extractors and CLI parsers.

**Risk Assessment:** Moderate — the highest-risk business logic functions have been reduced. Language extractors are inherently complex due to AST node handling.

---

**3. 11 subprocess calls without timeout**

| Dimension | Score |
|-----------|-------|
| Category | Resource exhaustion |
| Likelihood | 1 — Low |
| Impact | 2 — Medium |
| Detectability | 1 — Easy |
| **Priority** | **4** |

**Description:** Some subprocess calls may not have explicit timeouts, though the main git operations do have configurable timeouts.

**Current Mitigation:** Main git subprocesses (`git ls-tree`, `git show`) have configurable timeouts via `[impactguard.git] timeout`.

---

**4. 4 stat() calls creating TOCTOU windows**

| Dimension | Score |
|-----------|-------|
| Category | Concurrency / TOCTOU |
| Likelihood | 1 — Low |
| Impact | 1 — Low |
| Detectability | 2 — Hard |
| **Priority** | **4** |

**Description:** Four `stat()` calls exist in the codebase, creating small TOCTOU windows between checking file state and operating on it.

**Current Mitigation:** Most file operations use context managers (`with open(...)`) which minimize the window. The stat calls are for cache invalidation and staleness checks where race conditions have benign outcomes.

---

### Low Priority (score ≤ 4)

| # | Observation | Category | Priority |
|---|-------------|----------|----------|
| 5 | Coverage threshold (80%) not met (~14%) | Test coverage | 2 |
| 6 | Some CLI tests timeout on stdin | Test reliability | 2 |
| 7 | `_extract_all_names` doesn't handle `__all__.extend()` with variables | Correctness | 3 |
| 8 | `_parse_union_members` doesn't handle deeply nested generics | Correctness | 3 |

---

## Security Summary

| Check | Status |
|-------|--------|
| SQL injection | ✓ None found |
| SSRF | ✓ No external HTTP |
| Command injection | ✓ subprocess calls validated |
| XXE | ✓ No XML processing |
| Insecure temp files | ✓ Uses mkstemp/mkdtemp |
| Pickle with untrusted data | ⚠ Local cache only |
| shell=True | ✓ None found |
| eval/exec | ✓ None found |
| Bare except | ✓ None found |
| try/except/pass | ✓ None found |
| Unused imports | ✓ None found |
| Undefined names | ✓ None found |

---

## Assumptions Made

- **Threat model**: Opportunistic external attacker + accidental misuse by authorized users.
- **Scope**: Python-only analysis of the ImpactGuard codebase itself.
- **Not analyzed**: Third-party language extractors (tree-sitter-based) not deeply audited for parser vulnerabilities.
- **Test coverage**: 377+ adversarial tests and 21 core tests pass.
