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
Dictionary mapping `fqname` to signature dictionary

---

#### `compare(old_path: str, new_path: str) -> dict[str, list[str]]`  # noqa: MC0001
Compare two signature snapshots and classify changes.

**Args:**
- `old_path`: Path to old signatures JSON file
- `new_path`: Path to new signatures JSON file

**Returns:**
Dictionary with keys:
- `breaking`: List of breaking change descriptions
- `nonbreaking`: List of non-breaking change descriptions

**Breaking Changes Detected:**
- Function removal
- Positional argument removal
- Positional argument reorder/rename
- Required positional argument addition
- Required kwonly argument addition
- `*args` removal
- `**kwargs` removal

**Non-Breaking Changes Detected:**
- Function addition
- Optional positional argument addition
- Optional kwonly argument addition

**Invariants:**
- Results are sorted and deduplicated
- Both outputs are always present (may be empty lists)

---

### Impact Analysis (`impact_analysis.py`)

#### `load_funcs(path: str) -> dict[str, dict[str, Any]]`
Load function signatures from JSON file.

**Args:**
- `path`: Path to JSON file

**Returns:**
Dictionary mapping `fqname` to signature dictionary

---

#### `load_calls(path: str) -> list[dict[str, Any]]`
Load call sites from JSON file.

**Args:**
- `path`: Path to JSON file

**Returns:**
List of call site dictionaries

---

#### `required_positional(func: dict[str, Any]) -> int`
Count required positional arguments.

**Args:**
- `func`: Function signature dictionary

**Returns:**
Number of required positional arguments

---

#### `total_positional(func: dict[str, Any]) -> int`
Count total positional arguments.

**Args:**
- `func`: Function signature dictionary

**Returns:**
Total number of positional arguments

---

#### `analyze(sigs_path: str, calls_path: str, runtime_path: str | None = None) -> list[dict[str, Any]]`
Analyze impact of signature changes on call sites.

**Args:**
- `sigs_path`: Path to signatures JSON file
- `calls_path`: Path to call sites JSON file
- `runtime_path`: Optional path to runtime data JSON

**Returns:**
List of impact issue dictionaries

---

### Runtime Impact (`runtime_impact.py`)

#### `load_funcs(path: str) -> dict[str, dict[str, Any]]`
Load function signatures from JSON file.

**Args:**
- `path`: Path to JSON file

**Returns:**
Dictionary mapping `fqname` to signature dictionary

---

#### `required_positional(func: dict[str, Any]) -> int`
Count required positional arguments.

**Args:**
- `func`: Function signature dictionary

**Returns:**
Number of required positional arguments

---

#### `total_positional(func: dict[str, Any]) -> int`
Count total positional arguments.

**Args:**
- `func`: Function signature dictionary

**Returns:**
Total number of positional arguments

---

### Risk Model (`risk_model.py`)

#### `get_severity(change_type: str) -> float`
Get severity score for a change type.

**Args:**
- `change_type`: String describing the change (e.g., "REMOVED", "REQUIRED POSITIONAL ADDED")

**Returns:**
Severity score between 0.0 and 1.0

**Severity Scores:**
- REMOVED: 1.0
- REQUIRED POSITIONAL ADDED: 0.9
- POSITIONAL REORDER/RENAME: 0.8
- REQUIRED KWONLY ADDED: 0.9
- KWONLY REMOVED: 0.8
- *args REMOVED: 0.7
- **kwargs REMOVED: 0.7
- OPTIONAL POSITIONAL ADDED: 0.3
- OPTIONAL KWONLY ADDED: 0.3
- ADDED: 0.1

---

#### `exposure(count: int, max_count: int) -> float`
Calculate exposure score from call count.

**Args:**
- `count`: Number of times function was called
- `max_count`: Maximum call count across all functions

**Returns:**
Exposure score between 0.0 and 1.0
- Uses logarithmic scaling: `min(1.0, log(1 + count) / log(1 + max_count))`

---

#### `confidence(samples: int, threshold: int = 100) -> float`
Calculate confidence from sample count.

**Args:**
- `samples`: Number of runtime samples collected
- `threshold`: Sample count for full confidence (default: 100)

**Returns:**
Confidence score between 0.0 and 1.0

---

#### `classify(severity: float, count: int, max_count: int, samples: int) -> tuple[str, float, float]`
Classify risk level based on severity, exposure, and confidence.

**Args:**
- `severity`: Severity score (0.0 to 1.0)
- `count`: Call count
- `max_count`: Maximum call count
- `samples`: Runtime sample count

**Returns:**
Tuple of (risk_level, exposure, confidence) where risk_level is "HIGH", "MEDIUM", "LOW", or "UNKNOWN"

**Classification Rules:**
- If confidence < 0.3: return "UNKNOWN"
- If severity > 0.8 and exposure > 0.1: return "HIGH"
- If severity > 0.5 and exposure > 0.01: return "MEDIUM"
- Otherwise: return "LOW"

---

#### `compute_risk(severity: float, exposure_val: float, confidence_val: float) -> float`
Compute risk as S × E × C.

**Args:**
- `severity`: Severity score
- `exposure_val`: Exposure score
- `confidence_val`: Confidence score

**Returns:**
Risk score (product of the three inputs)

---

### Risk Gate (`risk_gate.py`)

The following functions are re-exported from `risk_model.py` for convenience:

#### `get_severity(change_type: str) -> float`
Get severity score for a change type (re-exported from `risk_model.get_severity`).

---

#### `exposure(count: int, max_count: int) -> float`
Calculate exposure score (re-exported from `risk_model.exposure`).

---

#### `confidence(samples: int, threshold: int = 100) -> float`
Calculate confidence (re-exported from `risk_model.confidence`).

---

#### `classify(severity: float, count: int, max_count: int, samples: int) -> tuple[str, float, float]`
Classify risk level (re-exported from `risk_model.classify`).

---

#### `run(diff_path: str, runtime_path: str, output_path: str | None = None) -> list[dict[str, Any]]`
Run risk analysis pipeline combining diff and runtime data.

**Args:**
- `diff_path`: Path to diff text file
- `runtime_path`: Path to runtime data JSON
- `output_path`: Optional output path for report JSON

**Returns:**
List of risk report items with keys: function, risk, change, exposure, confidence, details

---

#### `main(diff_path: str | None = None, runtime_path: str | None = None, output_path: str | None = None) -> list[dict[str, Any]]`
CLI entry point for risk gate.

---

### Patch Confidence (`patch_confidence.py`)

#### `compute_confidence(target_certainty: float, structural: float, semantic: float, complexity: float) -> float`
Score patch confidence by multiplying target × structural × semantic × complexity.

**Args:**
- `target_certainty`: Confidence in target identification (0.0 to 1.0)
- `structural`: Safety of structural changes (0.0 to 1.0)
- `semantic`: Semantic risk factor (0.0 to 1.0)
- `complexity`: Penalty for code complexity (0.0 to 1.0)

**Returns:**
Confidence score between 0.0 and 1.0

---

#### `classify(conf: float) -> str`
Classify patch confidence into categories.

**Args:**
- `conf`: Confidence score (0.0 to 1.0)

**Returns:**
"HIGH", "MEDIUM", "LOW", or "UNKNOWN"

**Classification Rules:**
- conf >= 0.75: "HIGH"
- conf >= 0.4: "MEDIUM"
- conf >= 0.2: "LOW"
- Otherwise: "UNKNOWN"

---

#### `get_target_certainty(file_match: bool, lineno_match: bool, name_only_match: bool) -> float`
Calculate target certainty score.

**Args:**
- `file_match`: Whether file matches
- `lineno_match`: Whether line number matches
- `name_only_match`: Whether name-only match

**Returns:**
- If file_match and lineno_match: 1.0
- If name_only_match: 0.5
- Otherwise: 0.2

---

#### `get_structural_safety(change_type: str) -> float`
Calculate structural safety score.

**Args:**
- `change_type`: Description of the change

**Returns:**
- If "default" or "optional" in change_type: 1.0
- If "kwarg" in change_type: 0.8
- If "positional" in change_type: 0.3
- Otherwise: 0.5

---

#### `get_semantic_risk(change_type: str) -> float`
Calculate semantic risk score.

**Args:**
- `change_type`: Description of the change

**Returns:**
- If "required" in change_type: 0.6
- Otherwise: 1.0

---

#### `get_complexity_penalty(is_multiline: bool, has_decorators: bool, has_complex_annotations: bool, is_nested: bool) -> float`
Calculate complexity penalty.

**Args:**
- `is_multiline`: Whether change spans multiple lines
- `has_decorators`: Whether function has decorators
- `has_complex_annotations`: Whether function has complex type annotations
- `is_nested`: Whether function is nested

**Returns:**
Penalty factor starting at 1.0, multiplied by:
- 0.7 if multiline
- 0.5 if has decorators
- 0.5 if has complex annotations
- 0.5 if nested

---

#### `classify_with_factors(target: float, structural: float, semantic: float, complexity: float) -> tuple[str, dict[str, float]]`
Classify patch and return confidence factors.

**Args:**
- `target`: Target certainty score
- `structural`: Structural safety score
- `semantic`: Semantic risk score
- `complexity`: Complexity penalty

**Returns:**
Tuple of (risk_level, factors_dict) where factors_dict contains:
- `target`: Target certainty
- `structure`: Structural safety
- `semantic`: Semantic risk
- `complexity`: Complexity penalty
- `final`: Final confidence score

---

### Enforce Gate (`enforce_gate.py`)

#### `enforce(diff_path: str, runtime_path: str, output_path: str | None = None) -> int`
Run risk analysis and enforce gate — blocks build on HIGH risk.

**Args:**
- `diff_path`: Path to diff text file
- `runtime_path`: Path to runtime data JSON file
- `output_path`: Optional path to write report JSON

**Returns:**
- `1` if any item has `risk == "HIGH"` (blocks build), printing `🔴 HIGH — {func}` for each
- `0` with warning if any item has `risk == "UNKNOWN"`, printing `⚠️ Warning: Unknown risk areas detected`
- `0` printing `✅ API risk acceptable` otherwise

---

#### `enforce_report(report_path: str) -> int`
Enforce gate from a pre-generated report JSON (backward-compatible single-argument form).

**Args:**
- `report_path`: Path to pre-generated risk report JSON file

**Returns:**
Same as `enforce()`.

---

### Report Generation (`generate_report.py`)

#### `color(level: str) -> str`
Get HTML color for risk level.

**Args:**
- `level`: Risk level ("HIGH", "MEDIUM", "LOW", "UNKNOWN")

**Returns:**
Hex color string

---

#### `generate_html(report_data: list[dict[str, Any]]) -> str`
Generate static HTML report from risk JSON.

**Args:**
- `report_data`: List of risk report dictionaries

**Returns:**
HTML content as string

---

#### `generate_html_from_file(risk_json_path: str, output_path: str | None = None) -> str`
Generate HTML report from JSON file path (file-based API matching SPEC).

**Args:**
- `risk_json_path`: Path to risk report JSON file
- `output_path`: Optional path to write HTML output

**Returns:**
HTML content as string

---

#### `main(report_path: str, output_path: str | None = None) -> None`
CLI entry point for report generation.

---

### Patch Generation (`patch_generator.py`)

#### `patch_add_default(func: dict[str, Any], param_name: str) -> tuple[str | None, str | None]`
Generate patch to add default value to parameter.

**Args:**
- `func`: Function signature dictionary
- `param_name`: Parameter name to patch

**Returns:**
Tuple of (patch_string, error_message)

---

#### `patch_call_site(call: dict[str, Any], func: dict[str, Any]) -> tuple[str | None, str | None]`
Generate patch for call site.

**Args:**
- `call`: Call site dictionary
- `func`: Function signature dictionary

**Returns:**
Tuple of (patch_string, error_message)

---

### CST Patch (`cst_patch.py`)

#### `patch_function(source: str, func_name: str, param_name: str) -> tuple[str | None, str | None]`
Patch function definition using CST to add default value.

**Args:**
- `source`: Source code string
- `func_name`: Function name
- `param_name`: Parameter name

**Returns:**
Tuple of (patched_source, error_message)

---

#### `patch_call(source: str, func_name: str, param_name: str) -> tuple[str | None, str | None]`
Patch function call to add missing argument.

**Args:**
- `source`: Source code string
- `func_name`: Function name
- `param_name`: Parameter name

**Returns:**
Tuple of (patched_source, error_message)

---

### Suggest Fixes (`suggest_fixes.py`)

#### `suggest(func: dict[str, Any], issues: list[dict[str, Any]]) -> list[str]`
Generate fix suggestions for issues.

**Args:**
- `func`: Function dictionary
- `issues`: List of issue dictionaries

**Returns:**
List of suggestion strings

---

#### `get_line(file: str, lineno: int) -> str`
Get source line from file.

**Args:**
- `file`: File path
- `lineno`: Line number

**Returns:**
Source line or empty string

---

#### `enrich_with_fixes(report_item: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]`
Enrich report item with patch information.

**Args:**
- `report_item`: Report item dictionary
- `issues`: List of issue dictionaries

**Returns:**
List of fix dictionaries

---

### Trace Calls (`trace_calls.py`)

#### `trace(func: Callable[..., Any]) -> Callable[..., Any]`
Decorator to trace function calls at runtime.

**Args:**
- `func`: Function to trace

**Returns:**
Wrapped function that records call information

---

#### `dump(path: str = ".runtime_calls.json") -> None`
Dump collected trace data to JSON file.

**Args:**
- `path`: Output file path

---

#### `install_tracer(module: object, prefix: str | None = None) -> None`
Install tracer on all functions in a module.

**Args:**
- `module`: Module to trace
- `prefix`: Optional module prefix filter

---

### Trace Calls Prod (`trace_calls_prod.py`)

#### `should_sample() -> bool`
Determine if current call should be sampled.

**Returns:**
True if call should be sampled (based on SAMPLE_RATE)

---

#### `trace(func: Callable[..., Any]) -> Callable[..., Any]`
Production tracer decorator with periodic flush.

---

#### `flush(path: str = "/tmp/runtime_calls.json") -> None`
Flush collected data to file.

---

#### `install_tracer(module: object, prefix: str | None = None) -> None`
Install production tracer on module.

---

### Module Analysis (`analyze_module.py`)

#### `analyze(path: str) -> dict[str, Any] | None`
Analyze Python module and extract function calls with scope tracking.

**Args:**
- `path`: Path to Python file

**Returns:**
Dictionary with keys: `file`, `calls` (list of call dictionaries)

**Call Dictionary Keys:**
- `fqname`: Fully qualified function name
- `file`: Source file
- `lineno`: Line number
- `args`: Number of positional arguments
- `kwargs`: List of keyword argument names
- `starargs`: Whether *args present
- `kwargs_any`: Whether **kwargs present

---

#### `analyze_calls(files: list[str]) -> list[dict[str, Any]]`
Analyze call sites across multiple Python files.

**Args:**
- `files`: List of Python file paths

**Returns:**
Flat list of call site dictionaries from all files (same keys as above)

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

#### `impactguard enforce <diff> <runtime> [-o output]`
Run risk analysis and enforce gate — blocks on HIGH risk. Returns exit code 1 if HIGH risk detected.

#### `impactguard suggest <report> [-o output]`
Generate fix suggestions from a risk report JSON file.

#### `impactguard patch <file> <func_name> <param_name> [--type function|call] [-o output]`
Generate CST-based patches for a source file.

#### `impactguard trace install <module> [--prefix PREFIX]`
Install runtime tracer for a module.

#### `impactguard trace dump [output]`
Dump collected runtime trace data.

#### `impactguard check <old> <new> [runtime] [output]`
Run full ImpactGuard pipeline check (default mode).

#### `impactguard check-commits <old_ref> <new_ref> [--files file1.py file2.py] [runtime] [output]`
Compare two git commits and run pipeline.

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
      {"name": "arg1", "has_default": false},
      {"name": "arg2", "has_default": true}
    ],
    "kwonly": [],
    "vararg": false,
    "kwarg": true,
    "class_name": null
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
    "class_name": "ClassName"
  }
]
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
    "details": "called 42 times"
  }
]
```

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
