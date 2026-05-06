# SPEC.md — ImpactGuard

## Purpose

ImpactGuard is a lightweight API impact analyzer for Python projects. It tracks function signatures across commits, detects breaking changes, and analyzes call-site impact using both static and runtime techniques. The tool helps maintain API stability by providing actionable reports on how code changes affect downstream callers.

## Scope

### In Scope

- AST-based function signature extraction from Python source files
- Semantic comparison between signature snapshots (breaking vs non-breaking changes)
- Call-site extraction and impact analysis
- Type-aware module analysis with scope tracking
- Runtime call tracing during test execution
- Risk assessment using S × E × C model (severity × exposure × confidence)
- HTML report generation from risk analysis
- Patch confidence scoring with target certainty, structural safety, semantic risk, and complexity penalty
- CST-based patch generation that preserves source formatting
- CLI interface with subcommands for all major operations
- **Class context in signatures** (ClassName.method format)
- **Automatic changelog generation** from signature diffs
- **Post-commit hook for automatic signature tracking**
- **CI integration for enforcement**

### Out of Scope

- Full type inference engine (relies on annotations and simple constructor inference)
- Dynamic dispatch resolution
- Higher-order function analysis
- Runtime tracing of production code outside test runs

## Public API / Interface

### Signature Extraction (`extract_signatures.py`)

#### `extract(files: list[str]) -> list[dict[str, Any]]`
Extract function signatures from Python files using AST parsing.

**Args:**

- `files`: List of Python file paths (strings or Path objects)

**Returns:**
List of signature dictionaries with keys:

- `fqname`: Fully qualified name (`file:function` or `file:ClassName.method`)
- `name`: Function name (or `ClassName.method` for methods)
- `file`: Source file path
- `lineno`: Starting line number
- `end_lineno`: Ending line number
- `positional`: List of positional arg dicts with `name` and `has_default`
- `kwonly`: List of keyword-only arg dicts
- `vararg`: Boolean indicating `*args` presence
- `kwarg`: Boolean indicating `**kwargs` presence
- `class_name`: Class name if function is a method (None for top-level functions)

---

#### `serialize_function(node: ast.FunctionDef | ast.AsyncFunctionDef, file: str) -> dict[str, Any]`
Convert an AST function node to a signature dictionary.

**Args:**

- `node`: AST node (FunctionDef or AsyncFunctionDef)
- `file`: Source file path

**Returns:**
Signature dictionary (see `extract` return format)

---

### Signature Comparison (`compare_signatures.py`)

#### `load(path: str) -> dict[str, dict[str, Any]]`
Load signatures from a JSON file into a dictionary keyed by fqname.

**Args:**

- `path`: Path to signatures JSON file

**Returns:**
Dictionary with keys: `file`, `calls` (list of call dictionaries)

---

#### `analyze_calls(files: list[str]) -> list[dict[str, Any]]`
Analyze call sites across multiple Python files.

**Args:**

- `files`: List of Python file paths.

**Returns:**
Flat list of call site dictionaries from all files, each with keys:
`fqname`, `file`, `lineno`, `args`, `kwargs`, `starargs`, `kwargs_any`.

---

### Extract Calls (`extract_calls.py`)

#### `extract(path: Path) -> list[dict[str, Any]]`
Extract function calls from Python file.

**Args:**

- `path`: Path to Python file

**Returns:**
List of call dictionaries (see `analyze` for format)

---

### CLI Interface (`__main__.py`)

The `impactguard` command provides the following subcommands:

#### `impactguard extract [files...]`
Extract function signatures from Python files. Reads file list from stdin if no arguments provided.

#### `impactguard compare <old> <new> [-o output]`
Compare two signature snapshots and report breaking/non-breaking changes.

#### `impactguard analyze <signatures> <calls> [runtime]`
Analyze impact of signature changes on call sites.

#### `impactguard risk <diff> <runtime> <output>`
Run risk analysis pipeline.

#### `impactguard report <report> [output]`
Generate HTML report from risk JSON.

#### `impactguard trace install <module> [--prefix PREFIX]`
Install runtime tracer for a module.

#### `impactguard trace dump [output]`
Dump collected runtime trace data.

#### `impactguard check <old> <new> [runtime] [output] [--watch]`
Run full ImpactGuard pipeline check (default mode).

- `--watch`: Re-run automatically whenever any `*.py` file in `old` or `new` changes.

#### `impactguard check-commits <old_ref> <new_ref> [--files file1.py file2.py] [runtime] [output]`
Compare two git commits and run pipeline.

#### `impactguard enforce <diff> <runtime> [-o output] [--block-unknown]`
Block the CI pipeline on HIGH risk (or UNKNOWN risk when `--block-unknown` is set).

- `--block-unknown`: Treat UNKNOWN risk as a blocking condition.

#### `impactguard baseline save [files...] [--path PATH]`
Save current signatures as the new baseline.

- `files`: Python files to snapshot (default: all `*.py` in cwd recursively).
- `--path`: Path to the baseline JSON file (default: `.impactguard_baseline.json`).

#### `impactguard baseline status [--path PATH]`
Show information about the stored baseline.

#### `impactguard baseline compare [files...] [--path PATH] [-o output]`
Compare current code against the stored baseline.  Exits 1 when breaking changes are found.

#### `impactguard semver <old> <new> [--current-version VERSION] [-o output]`
Suggest a semver bump (major / minor / patch) from two signature JSON snapshots.

- `--current-version`: Current version string (e.g. `1.2.3`).  When provided, the
  recommended *next* version is also printed.
- `-o`: Write the recommendation as JSON to this file.

#### `impactguard install-hooks [repo_path] [--pre] [--post] [--both]`
Install git hooks for ImpactGuard.

- `repo_path`: Path to git repository (default: current directory)
- `--pre`: Install pre-commit hook only
- `--post`: Install post-commit hook only
- `--both`: Install both hooks (default)
- Pre-commit hook: Extracts signatures from staged Python files
- Post-commit hook: Updates `.signatures.txt` after commit

#### `impactguard generate-changelog [--old-files file1.py file2.py] [--new-files file3.py file4.py] [--old-ref REF] [--new-ref REF] [output]`
Generate changelog from signature diffs.

- `--old-files`: Old Python files (alternative to --old-ref)
- `--new-files`: New Python files (alternative to --new-ref)
- `--old-ref`: Old git reference (commit, branch, tag)
- `--new-ref`: New git reference (commit, branch, tag)
- `output`: Output file for changelog (default: stdout)
- Generates markdown changelog with sections: Added, Changed, Removed, Breaking Changes

---

### Convenience Functions (in `__init__.py`)

#### `extract_signatures(files: list[str]) -> list[dict[str, Any]]`
Wrapper for `extract_signatures.extract()`.

#### `compare_signatures(old_path: str, new_path: str) -> dict[str, list[str]]`
Wrapper for `compare_signatures.compare()`.

#### `analyze_impact(sigs_path: str, calls_path: str, runtime_path: str | None = None) -> list[dict[str, Any]]`
Wrapper for `impact_analysis.analyze()`.

### New Modules (added in this version)

#### `config.py` — Runtime configuration

- `load_config(config_path)` — Load and merge `impactguard.toml` with built-in defaults.
- `get_config()` — Lazy singleton accessor.
- `reload_config(config_path)` — Force re-read from disk.
- `get(section, key, default)` — Shortcut for `config["impactguard"][section][key]`.

#### `semver.py` — Semver recommendation

- `suggest_semver(comparison)` — Returns `"major"`, `"minor"`, or `"patch"`.
- `format_semver_recommendation(comparison, current_version)` — Returns structured dict.

#### `baseline.py` — Historical baseline storage

- `save_baseline(files, path, metadata)` — Snapshot signatures to a JSON file.
- `load_baseline(path)` — Load a previously saved baseline.
- `compare_with_baseline(new_files, baseline_path)` — Compare new code against stored baseline.
- `baseline_exists(path)` — Check whether a baseline file is present.

---

## Data Formats

### Signatures JSON
```json
[
  {
    "fqname": "src/module.py:function_name",
    "name": "function_name",
    "file": "src/module.py",
    "lineno": 10,
    "end_lineno": 15,
    "positional": [
      {"name": "arg1", "has_default": false, "type": "int"},
      {"name": "arg2", "has_default": true,  "type": "str"}
    ],
    "kwonly": [],
    "vararg": false,
    "kwarg": true,
    "class_name": null,
    "return_type": "bool",
    "decorators": ["staticmethod"],
    "is_async": false
  },
  {
    "fqname": "src/module.py:ClassName.method_name",
    "name": "ClassName.method_name",
    "file": "src/module.py",
    "lineno": 20,
    "end_lineno": 25,
    "positional": [...],
    "kwonly": [],
    "vararg": false,
    "kwarg": false,
    "class_name": "ClassName",
    "return_type": null,
    "decorators": [],
    "is_async": true
  }
]
```

**New fields (added in this version):**

- `return_type`: Return annotation string (e.g. `"str"`, `"list[int]"`) or `null`
- `decorators`: List of decorator expression strings (e.g. `["staticmethod", "deprecated"]`)
- `is_async`: `true` when the function is `async def`
- `positional[*].type` / `kwonly[*].type`: Type annotation string or `null`

### Baseline JSON
```json
{
  "signatures": [...],
  "metadata": {
    "saved_at": "2026-05-05T19:49:38Z",
    "files_count": 12
  }
}
```

### Semver Recommendation JSON
```json
{
  "bump": "major",
  "reason": "3 breaking change(s) detected — callers must update",
  "breaking_count": 3,
  "nonbreaking_count": 1,
  "next_version": "2.0.0"
}
```

### Call Sites JSON
```json
[
  {
    "name": "target_function",
    "lineno": 25,
    "args": 2,
    "kwargs": ["arg1", "arg2"],
    "has_starargs": false,
    "has_kwargs": false,
    "file": "src/caller.py"
  }
]
```

### Runtime Data JSON
```json
[
  {
    "function": "src/module.py:function_name",
    "count": 42
  }
]
```

### Risk Report JSON
```json
[
  {
    "function": "src/module.py:function_name",
    "risk": "HIGH",
    "change": "REMOVED",
    "exposure": 0.85,
    "confidence": 0.95,
    "details": "called 42 times",
    "transitive": false
  }
]
```

**New fields:**
- `transitive`: `true` when this entry represents an *indirect* caller rather than a
  directly broken call site.  Transitive entries always have `"risk": "LOW"`.

---

## Edge Cases
1. **Empty input files list**: `extract([])` returns empty list
2. **Syntax errors in source**: Files with parse errors are silently skipped
3. **Missing JSON files**: `load()` and `compare()` should handle missing files gracefully
4. **Empty signature snapshots**: Comparison should handle empty old or new snapshots
5. **Zero runtime samples**: `confidence(0)` returns `0.0`, `exposure(0, N)` returns `0.0`
6. **Single-element input**: Functions with no arguments, single call site
7. **Large input**: Projects with thousands of functions (must handle efficiently)
8. **Unicode in source**: Python files with non-ASCII characters
9. **Nested functions**: Inner functions are included with their names (no class/function context)
10. **Class methods**: Now include class context in `fqname` (`ClassName.method`) and `class_name` field
11. **Files with only classes**: No functions to extract (returns empty list)
12. **Private symbols**: Functions whose leaf name starts with `_` are excluded from comparison
    by default (`include_private = false` in config).  Pass `include_private=True` to `compare()`
    or set `[impactguard.analysis] include_private = true` to include them.
13. **Missing baseline**: `compare_with_baseline()` raises `FileNotFoundError` when no baseline
    has been saved yet.
14. **Non-semver current_version**: `_increment()` appends `-next` instead of failing.

---

## Performance & Constraints

### Performance Requirements
- Signature extraction: O(F × L) where F is number of files, L is average lines per file
- Signature comparison: O(S) where S is total number of signatures
- Memory: Should handle projects with 10,000+ functions within 512MB RAM

### Constraints
- Requires Python 3.11+ (uses `ast` module features)
- Runtime tracing adds overhead; use sampling in production (`trace_calls_prod.py`)
- External dependency: `libcst>=0.4.0` for CST-based patching
- No network access required
- No database dependencies

### Forbidden Patterns
- Do not use `eval()` or `exec()` on user code
- Do not modify source files during analysis (except patches which are explicit)
- Do not introduce circular imports within the package
- All imports should be at the top of the module (lazy imports used only in CLI for performance)

---

## Invariants

### All Modules
- Type annotations present on all public functions (mypy strict mode compliant)
- Ruff format clean (0 issues)
- Ruff check clean (0 issues)
- Prospector clean (0 warnings)
- Semgrep clean (0 findings)
- MyPy clean (0 errors in strict mode)

### Signature Extraction
- Output is sorted by `fqname` for stable comparison
- Handles both `def` and `async def`
- Skips files that fail to parse (with silent continuation)

### Risk Analysis
- Coverage requirement: ≥ 80% (currently at 73.33%)
- All edge cases listed above have corresponding tests
- Tests pass with 0 failures (currently 80 passed)
