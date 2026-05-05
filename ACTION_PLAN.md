# ImpactGuard — Action Plan

**Date**: 2026-05-04  
**Status**: Ready for Execution  
**Branch**: `master`

---

## Executive Summary

This action plan addresses 16 verified issues in the ImpactGuard codebase:
- **5 confirmed bugs** (divergent risk tables, wrong API signatures, data loss in flush)
- **4 missing CLI/API features** (suggest, patch, analyze_calls, version dynamic)
- **7 structural issues** (incomplete exports, branch mismatch, stale docs)

**Priority**: Fix bugs first, then complete CLI/API surface, then clean up structural issues.

---

## ✅ Verified Bugs (Fix Immediately)

### Bug 1: Dead code in `impact_analysis.py` — ✅ ALREADY FIXED
- **Commit**: `fa80dd6` — "chore: remove last __main__ block"
- **Status**: File ends at line 157, no dead code remains

---

### Bug 2: `enforce_gate.enforce()` Has Wrong API
- **File**: `src/impactguard/enforce_gate.py:5`
- **Problem**: `enforce(report_path)` takes one arg (pre-generated report JSON)
- **SPEC says**: `enforce(diff_path, runtime_path, output_path=None)` — completely different
- **Decision needed**: Keep simple `enforce(report_path)` (matches CI usage) and update SPEC, OR rewrite to match SPEC
- **Recommended**: Keep simple version, update SPEC to match code
- **Action**:
  ```python
  # Current (keep this):
  def enforce(report_path: str) -> int:
      report = json.load(open(report_path))
      # ...check for HIGH risk
  ```

---

### Bug 3: Divergent Risk Score Tables (HIGH PRIORITY)
- **Files**:
  - `src/impactguard/risk_model.py` — CANONICAL (has `"REQUIRED POSITIONAL ADDED": 0.9`)
  - `src/impactguard/risk_gate.py:7-16` — DIVERGENT (has `"REQUIRED": 0.9`)
  - `src/impactguard/impact_analysis.py:31-44` — DIVERGENT (same as risk_gate)

- **Problem**: Same change type gets DIFFERENT severity scores depending on which module processes it
- **Example**:
  - `risk_model.py`: `"REQUIRED POSITIONAL ADDED": 0.9`
  - `risk_gate.py`: `"REQUIRED": 0.9` — won't match `"REQUIRED POSITIONAL ADDED"`

- **Fix**:
  1. Delete `SEVERITY_SCORES`, `get_severity()`, `exposure()`, `confidence()`, `classify()` from `risk_gate.py`
  2. Delete same from `impact_analysis.py`
  3. Import from `risk_model.py`:
     ```python
     from .risk_model import SEVERITY_SCORES, get_severity, exposure, confidence, classify
     ```

---

### Bug 4: `generate_html()` Signature Mismatch
- **File**: `src/impactguard/generate_report.py:14`
- **Problem**: `generate_html(report_data)` takes parsed Python list
- **SPEC says**: `generate_html(risk_json_path, output_path=None)` taking file paths
- **Current exports in `__init__.py:69`**: Exports the low-level version
- **Fix**:
  ```python
  # generate_report.py — add file-based wrapper:
  def generate_html_from_file(risk_json_path: str, output_path: str | None = None) -> str:
      """Generate HTML report from JSON file (matches SPEC API)."""
      report = json.load(open(risk_json_path))
      html = generate_html(report)
      if output_path:
          with open(output_path, "w") as f:
              f.write(html)
      return html
  ```
  Update `__init__.py` to export `generate_html_from_file` as public API.

---

### Bug 5: `trace_calls_prod.flush()` Clears Data
- **File**: `src/impactguard/trace_calls_prod.py:44-50`
- **Problem**: `COUNTS.clear()` on line 50 loses all data if process crashes after flush
- **Fix**:
  ```python
  def flush(path: str = "/tmp/runtime_calls.json") -> None:
      data = dict(COUNTS)
      # Atomic write: write to temp, then rename
      import tempfile, os
      with tempfile.NamedTemporaryFile(mode='w', dir=os.path.dirname(path) or '.', delete=False) as f:
          json.dump(data, f)
          temp_path = f.name
      os.rename(temp_path, path)
      # DON'T clear — let atexit handler do it, or accumulate
  
  import atexit
  atexit.register(lambda: flush("/tmp/runtime_calls_final.json"))
  ```

---

## ✅ Missing Functionality

### Missing 6: No `suggest` or `patch` CLI Subcommands
- **Files exist**: `suggest_fixes.py`, `cst_patch.py` — but no CLI entry points
- **`__init__.py` exports** (lines 25-26, 75-78): `suggest`, `patch_function`, `patch_call` ARE exported
- **Missing**: `cmd_suggest()` and `cmd_patch()` in `__main__.py`
- **Fix**: Add to `__main__.py`:
  ```python
  def cmd_suggest(args: argparse.Namespace) -> int:
      from .suggest_fixes import suggest
      # ... wire up CLI args
  
  def cmd_patch(args: argparse.Namespace) -> int:
      from .cst_patch import patch_function
      # ... wire up CLI args
  ```

---

### Missing 7: No `extract-calls` CLI — ❌ REVIEW WAS WRONG
- **Status**: ✅ ALREADY EXISTS
- **Evidence**: `__main__.py:78-97` has `cmd_extract_calls()`, lines 360-367 wire it to `extract-calls` subcommand
- **Action**: None needed

---

### Missing 8: `analyze_module.analyze()` Not Exported
- **File**: `src/impactguard/analyze_module.py` — has class `Analyzer`, not standalone `analyze()`
- **`__init__.py:9`**: Imports `analyze as analyze_module` from `.analyze_module`
- **SPEC mentions**: `analyze_calls()` — function doesn't exist
- **Decision needed**:
  - **A)** Add `analyze_calls()` wrapper to `analyze_module.py`, export in `__init__.py`
  - **B)** Remove `analyze_calls()` from SPEC (it's documentation-only)
- **Recommended**: Option A — add the function

---

### Missing 9: `runtime_impact.py` Only a Script
- **File**: `src/impactguard/runtime_impact.py` — only has `if __name__ == "__main__"` block
- **Fix**: Wrap logic in `analyze(signatures, calls)` function, export in `__init__.py`

---

## ✅ Structural Issues

### Issue 10: Makefile Uses Old Paths — ❌ REVIEW WAS WRONG
- **Status**: `Makefile` does NOT exist (`ls: cannot access 'Makefile'`)
- **But**: README.md lines 70, 74-79 reference `Makefile` and `make signatures`, etc.
- **Fix**: Either create `Makefile`, or remove references from README

---

### Issue 11: CI Triggers on `master`, Badges Point to `main` (HIGH PRIORITY)
- **CI**: `.github/workflows/ci.yml:5` — `branches: [master]`
- **README**: Line 7 — `.../branch/main/graph/badge.svg`
- **Actual branch**: `master` (confirmed by `git branch`)
- **Decision needed**:
  - **A)** Keep `master`, fix README badges to point to `master`
  - **B)** Migrate repo to `main` (requires `git branch -m master main`, force push, update GitHub settings)
- **Recommended**: Option A (keep `master`, fix README) — less disruptive

---

### Issue 12: Version Hardcoded in `__main__.py`
- **File**: `src/impactguard/__main__.py:315`
- **Problem**: `version="%(prog)s 0.1.0"` — literal string, `.bumpversion.cfg` won't update it
- **Fix**:
  ```python
  from . import __version__
  # ...
  parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
  ```

---

### Issue 13: `__all__` Incomplete in `__init__.py`
- **Missing from `__all__`** (lines 49-91):
  - `SEVERITY_SCORES` (imported line 34)
  - `get_structural_safety` (imported line 21, in `__all__`? No, not listed)
  - Wait, checking... line 68: `get_structural_safety` IS in `__all__`
  - `classify_with_factors` — imported in `pipeline.py` but NOT in `__init__.py` at all
- **Fix**: Add missing items to `__all__`, decide if `classify_with_factors` should be public

---

### Issue 14: `out.json` Committed — ❌ REVIEW WAS WRONG
- **Status**: `out.json` does NOT exist (`ls: cannot access 'out.json'`)
- **Action**: None needed

---

### Issue 15: `test/` Directory Exists Alongside `tests/`
- **Status**: ✅ Confirmed — `test/` is tracked by git with 4 files
- **Files**: `test/s/test_cli_fixed.py`, `test/s/test_coverage_boost.py`, etc.
- **Fix**:
  ```bash
  mv test/s/* tests/
  git rm -r test/
  rmdir test/
  ```

---

### Issue 16: Class/Method Context Missing — ❌ REVIEW WAS WRONG
- **Status**: ✅ ALREADY IMPLEMENTED
- **Evidence**: `extract_signatures.py:37-42` — `fqname = f"{file}:{class_name}.{node.name}"`
- **Action**: None needed

---

## Execution Plan (Prioritized)

### **Phase 1: Fix Bugs (High Priority) — Est. 2 hours**

1. **Fix Bug 3**: Delete duplicate risk functions from `risk_gate.py` and `impact_analysis.py`
   - Import from `risk_model.py` instead
   - Test: Run `pytest tests/test_risk_*.py`

2. **Fix Bug 4**: Add `generate_html_from_file()` to `generate_report.py`
   - Export in `__init__.py`
   - Update SPEC.md to match

3. **Fix Bug 5**: Fix `trace_calls_prod.flush()` data loss
   - Use atomic write pattern
   - Add `atexit` handler

4. **Fix Bug 2**: Decide on `enforce()` API
   - Recommended: Keep simple version, update SPEC

---

### **Phase 2: CLI Completeness — Est. 1 hour**

5. **Add `cmd_suggest()` and `cmd_patch()`** to `__main__.py`
   - Wire to `suggest_fixes.suggest()` and `cst_patch.patch_function()`
   - Add `--output` option to `cmd_extract()` (Missing 7 from earlier report)

6. **Fix Issue 12**: Make `--version` dynamic in `__main__.py`

---

### **Phase 3: Exports & API Surface — Est. 1 hour**

7. **Fix Issue 13**: Complete `__all__` in `__init__.py`
   - Add `SEVERITY_SCORES`, verify all imports are listed

8. **Fix Missing 8**: Add `analyze_calls()` to `analyze_module.py` (or remove from SPEC)

9. **Fix Missing 9**: Wrap `runtime_impact.py` logic in functions

---

### **Phase 4: Repository Hygiene — Est. 30 minutes**

10. **Fix Issue 11**: Either:
    - Keep `master`, fix README badges to `master`, OR
    - Migrate to `main` (requires GitHub settings update)

11. **Fix Issue 15**: Merge `test/` into `tests/`, delete `test/`

12. **Fix Issue 10**: Either create `Makefile` or remove README references

---

### **Phase 5: Documentation & Developer Experience — Est. 1 hour**

13. **Create `CONTRIBUTING.md`**
    - Cover: git hooks, release process, adding change-type detectors
    - Reference `AGENTS.md` for AI agents, `SPEC.md` for technical details

14. **Update `SPEC.md`** to match actual API
    - Remove `analyze_calls()` if not implemented
    - Fix `enforce()` signature documentation
    - Fix `generate_html()` signature documentation

---

## Q&A

1. **Branch strategy** (Issue 11): Keep `master` .

2. **`enforce()` API** (Bug 2):  rewrite to match SPEC?

3. **`analyze_calls()`** (Missing 8): Add function to `analyze_module.py`.

4. **`classify_with_factors`**: Should this be in `__all__` and public API.

---

## Success Criteria

- [ ] All 5 bugs fixed and verified with tests
- [ ] `impactguard suggest` and `impactguard patch` CLI commands work
- [ ] `--version` reads dynamically from `pyproject.toml`
- [ ] `__all__` is complete, no missing exports
- [ ] `test/` directory merged into `tests/`
- [ ] README badges match actual branch (`master` or `main`)
- [ ] `CONTRIBUTING.md` created
- [ ] `SPEC.md` updated to match actual API
- [ ] All 243 tests still pass after changes
- [ ] `mypy --strict src/` passes

---

**Next Step**: Wait for answers to 4 questions above, then execute Phase 1 immediately.
