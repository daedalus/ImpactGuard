# Failure Mode Analysis: ImpactGuard

**Date:** 2025-06-13
**Scope:** Full codebase audit — signature extraction, comparison, call graph, risk model, CLI, feedback loop
**Threat model:** Opportunistic external attacker + accidental misuse by authorized users

---

## Summary

ImpactGuard is a multi-language API impact analyzer that extracts function signatures via AST/tree-sitter, detects breaking changes, analyzes call-site impact, and assigns risk scores. It uses SQLite for persistent call graphs, subprocess calls for git operations, and a feedback-driven calibration loop. The primary risk surface is **silent correctness failures** — the tool can miss breaking changes or produce false-confidence risk scores without erroring, leading users to merge unsafe API changes.

---

## High Priority Failures (score ≥ 8)

### 1. Duplicate function definitions in `extract_signatures.py` and `impact_analysis.py`

| Dimension | Score |
|-----------|-------|
| Category | Correctness / Silent failure |
| Likelihood | 3 — High |
| Impact | 3 — High |
| Detectability | 3 — Silent |
| **Priority** | **9** |

**Description:** Functions `_has_ignore_comment`, `_extract_all_names`, `extract_reexports`, `_unparse_annotation`, `_decorator_name`, `build_call_graph`, `find_transitive_callers`, `_fqname_to_runtime_key` are **defined twice** in the same files. The second definition silently shadows the first.

**Impact:** The shadowed versions may have different behavior. For example, `extract_reexports` at line 50 uses `cached_ast_parse` while the duplicate at line 151 uses `ast.parse` directly. Callers get the second version unpredictably.

**Mitigation:** Delete all duplicate function definitions. Audit for other shadowed names across the codebase.

---

### 2. `_validate_git_ref` and `_validate_git_path` defined twice in `pipeline.py`

| Dimension | Score |
|-----------|-------|
| Category | Correctness / Security |
| Likelihood | 3 — High |
| Impact | 3 — High |
| Detectability | 3 — Silent |
| **Priority** | **9** |

**Description:** Both functions appear at lines 28–45/48–56 and again at lines 819–836/839–849. The second `_validate_git_path` (line 839) has a stricter check (`Path(path).is_absolute()`) not present in the first (line 48, which delegates to `is_safe_path`).

**Impact:** Depending on call order, different validation logic is applied, potentially allowing path traversal via git-ref paths.

**Mitigation:** Deduplicate. The `_validate_git_path` at line 48 uses the more robust `is_safe_path`; prefer that implementation.

---

### 3. FQNAME collision risk with duplicate basenames

| Dimension | Score |
|-----------|-------|
| Category | Silent correctness failure |
| Likelihood | 2 — Medium |
| Impact | 3 — High |
| Detectability | 2 — Hard |
| **Priority** | **7** |

**Description:** Two files with the same basename (e.g., `a/utils.py` and `b/utils.py`) produce identical fqnames when no `base_path` is supplied. The pipeline logs a warning (`fqname_collision_risk`) but proceeds.

**Impact:** Signatures from different files overwrite each other in the comparison dict, silently dropping breaking changes from one file.

**Mitigation:** Make `base_path` a required parameter in monorepo contexts; fail instead of warn on collision.

---

### 4. SQLite WAL contention under concurrent pipeline runs

| Dimension | Score |
|-----------|-------|
| Category | Concurrency / Resource exhaustion |
| Likelihood | 2 — Medium |
| Impact | 2 — Medium |
| Detectability | 2 — Hard |
| **Priority** | **6** |

**Description:** `CallGraphDB` uses `threading.Lock` for writes but the SQLite connection uses `check_same_thread=False` with `busy_timeout=5000`. Multiple concurrent pipeline runs on the same project can hit `SQLITE_BUSY` during writes.

**Impact:** Build/sync failures logged as warnings; call graph may be stale.

**Mitigation:** Use a file-level lock (`fcntl.flock`) in addition to the in-process `threading.Lock`, or serialize all DB access through a single connection process.

---

### 5. Feedback calibration writes to `impactguard.toml` without atomic replacement

| Dimension | Score |
|-----------|-------|
| Category | Data corruption / TOCTOU |
| Likelihood | 2 — Medium |
| Impact | 2 — Medium |
| Detectability | 2 — Hard |
| **Priority** | **6** |

**Description:** `apply_weights_to_config` reads the TOML file, modifies it in-memory, then writes back. Concurrent runs or interrupted writes can corrupt the config file.

**Impact:** Corrupted config causes fallback to defaults (benign) or parse errors.

**Mitigation:** Use write-to-temp + rename pattern for atomic file replacement.

---

### 6. `_resolve_target` ambiguity with multiple name matches

| Dimension | Score |
|-----------|-------|
| Category | Silent correctness failure |
| Likelihood | 2 — Medium |
| Impact | 2 — Medium |
| Detectability | 3 — Silent |
| **Priority** | **7** |

**Description:** `_resolve_target` at `impact_analysis.py:153` uses suffix matching (`f.endswith("." + target.split(".")[-1])`). Multiple signatures sharing the same leaf name produce ambiguous matches, and the function returns `None` (silently skipping the call site).

**Impact:** Impact analysis misses real arity mismatches for disambiguated calls.

**Mitigation:** Log a warning when multiple candidates match; prefer exact-match resolution.

---

### 7. Git subprocess timeout too short for large repos

| Dimension | Score |
|-----------|-------|
| Category | Resource exhaustion / Partial failure |
| Likelihood | 2 — Medium |
| Impact | 2 — Medium |
| Detectability | 1 — Easy |
| **Priority** | **5** |

**Description:** `git ls-tree` and `git show` in `_extract_git_ref_signatures` have 30-second timeouts. Large monorepos may legitimately exceed this.

**Impact:** Timeout logs warning and skips files, producing incomplete analysis.

**Mitigation:** Make git command timeouts configurable via `impactguard.toml`.

---

## Low Priority Failures (score ≤ 4)

| # | Failure | Category | Priority |
|---|---------|----------|----------|
| 8 | `_SUMMARIZE_FILES` truncation hides context | Usability | 3 |
| 9 | `_extract_all_names` only handles simple `__all__ = [...]` | Correctness | 4 |
| 10 | `_parse_union_members` doesn't handle nested generics | Correctness | 4 |
| 11 | `_is_effectively_public` inconsistent with `__all__` semantics | Correctness | 3 |
| 12 | `_inject_coverage_disclaimer` string replacement fragile | Robustness | 3 |
| 13 | No backup/rollback for `apply_safe_fixes` | Safety | 3 |
| 14 | `quick_check` collects all files recursively without limits | Performance | 4 |
| 15 | `_write_json` lacks error handling for disk-full | Reliability | 4 |
| 16 | `cmd_trace` whitelist bypass via module aliasing | Security | 4 |
| 17 | Config singleton `_config` never invalidated across test runs | Test isolation | 4 |
| 18 | Exposure normalization compresses scores in large codebases | Correctness | 7 |

---

## Key Mitigations

1. **Deduplicate all shadowed function definitions** — This is the highest-priority fix. Audit `extract_signatures.py`, `impact_analysis.py`, and `pipeline.py` for duplicate definitions and delete the redundant copies.

2. **Validate `_validate_git_ref`/`_validate_git_path` consistency** — Ensure only one implementation exists per function, using the most secure variant.

3. **Make exposure normalization configurable with an absolute reference** — Document and enforce `exposure_max_count` config to prevent scan-local compression.

4. **Add atomic config writes** — Use write-to-temp + rename pattern for `feedback.py`'s `apply_weights_to_config`.

5. **Add timeout configurability for git subprocesses** — Allow `impactguard.toml` to set git command timeouts for large repos.

---

## Assumptions Made

- **Threat model**: Opportunistic external attacker + accidental misuse by authorized users. Supply-chain attacks on tree-sitter dependencies not analyzed.
- **Scope**: Python-only analysis of the ImpactGuard codebase itself. Third-party language extractors (tree-sitter-based) not deeply audited.
- **Not analyzed**: `runtime_intelligence.py`, `sarif.py`, `generate_report.py` were read but not deeply traced for failure modes. The HTML report generation surface (XSS via function names) is unassessed.
- **Test coverage**: 3189+ tests exist but were not run during this analysis; test adequacy for the identified failure modes is unknown.
