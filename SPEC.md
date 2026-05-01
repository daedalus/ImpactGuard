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
- Automated patch suggestion with confidence scoring
- CST-based patch generation that preserves source formatting
- CLI interface with subcommands for all major operations
- Post-commit hook for automatic signature tracking

### Out of Scope
- Full type inference engine (relies on annotations and simple constructor inference)
- Dynamic dispatch resolution
- Higher-order function analysis
- Complete class context in signatures (currently flat function list)
- Runtime tracing of production code outside test runs

## Public API / Interface

### Signature Extraction

#### `extract(files: list[str | Path]) -> list[dict]`
Extract function signatures from Python files using AST parsing.

**Signature:**
```python
def extract(files: list) -> list[dict]:
```

**Args:**
- `files`: List of Python file paths (strings or Path objects)

**Returns:**
List of signature dictionaries with keys:
- `fqname`: Fully qualified name (`file:function`)
- `name`: Function name
- `file`: Source file path
- `lineno`: Starting line number
- `end_lineno`: Ending line number
- `positional`: List of positional arg dicts with `name` and `has_default`
- `kwonly`: List of keyword-only arg dicts
- `vararg`: Boolean indicating `*args` presence
- `kwarg`: Boolean indicating `**kwargs` presence

**Invariants:**
- Output is sorted by `fqname` for stable comparison
- Handles both `def` and `async def`
- Skips files that fail to parse (with silent continuation)

**Edge Cases:**
- Empty file list returns empty list
- Files with syntax errors are skipped
- Nested functions are included
- Decorators are ignored (not part of signature)

---

#### `serialize_function(node: ast.FunctionDef, file: str) -> dict`
Convert an AST function node to a signature dictionary.

**Signature:**
```python
def serialize_function(node, file: str) -> dict:
```

**Args:**
- `node`: AST node (FunctionDef or AsyncFunctionDef)
- `file`: Source file path

**Returns:**
Signature dictionary (see `extract` return format)

---

### Signature Comparison

#### `compare(old_path: str, new_path: str) -> dict`
Compare two signature snapshots and classify changes.

**Signature:**
```python
def compare(old_path: str, new_path: str) -> dict:
```

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
- Positional argument reorder/renaming
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

#### `load(path: str) -> dict`
Load signatures from a JSON file into a dictionary keyed by fqname.

**Signature:**
```python
def load(path: str) -> dict:
```

**Args:**
- `path`: Path to signatures JSON file

**Returns:**
Dictionary mapping `fqname` to signature dictionary

---

### Impact Analysis

#### `analyze(sigs_path: str, calls_path: str, runtime_path: str | None = None) -> list[dict]`
Analyze impact of signature changes on call sites.

**Signature:**
```python
def analyze(sigs_path: str, calls_path: str, runtime_path: str | None = None) -> list[dict]:
```

**Args:**
- `sigs_path`: Path to signatures JSON file
- `calls_path`: Path to call sites JSON file
- `runtime_path`: Optional path to runtime data JSON

**Returns:**
List of impact issue dictionaries

---

#### `analyze_calls(signatures_file: str, calls_file: str, runtime_file: str | None = None) -> list[dict]`
Type-aware impact analysis combining signatures with call-site data.

**Signature:**
```python
def analyze_calls(signatures_file: str, calls_file: str, runtime_file: str | None = None) -> list[dict]:
```

---

### Risk Model

#### `get_severity(change_type: str) -> float`
Get severity score for a change type.

**Signature:**
```python
def get_severity(change_type: str) -> float:
```

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

**Signature:**
```python
def exposure(count: int, max_count: int) -> float:
```

**Args:**
- `count`: Number of times function was called
- `max_count`: Maximum call count across all functions

**Returns:**
Exposure score between 0.0 and 1.0
- Uses logarithmic scaling: `min(1.0, log(1 + count) / log(1 + max_count))`

---

#### `confidence(samples: int, threshold: int = 100) -> float`
Calculate confidence from sample count.

**Signature:**
```python
def confidence(samples: int, threshold: int = 100) -> float:
```

**Args:**
- `samples`: Number of runtime samples collected
- `threshold`: Sample count for full confidence (default: 100)

**Returns:**
Confidence score between 0.0 and 1.0

---

#### `classify(severity: float, count: int, max_count: int, samples: int) -> tuple[str, float, float]`
Classify risk level based on severity, exposure, and confidence.

**Signature:**
```python
def classify(severity: float, count: int, max_count: int, samples: int) -> tuple[str, float, float]:
```

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

**Signature:**
```python
def compute_risk(severity: float, exposure_val: float, confidence_val: float) -> float:
```

**Args:**
- `severity`: Severity score
- `exposure_val`: Exposure score
- `confidence_val`: Confidence score

**Returns:**
Risk score (product of the three inputs)

---

### Risk Gate

#### `run(diff_path: str, runtime_path: str, output_path: str | None = None) -> list[dict]`
Run risk analysis pipeline combining diff and runtime data.

**Signature:**
```python
def run(diff_path: str, runtime_path: str, output_path: str | None = None) -> list[dict]:
```

**Args:**
- `diff_path`: Path to diff text file
- `runtime_path`: Path to runtime data JSON
- `output_path`: Optional output path for report JSON

**Returns:**
List of risk report items with keys: function, risk, change, exposure, confidence, details

---

#### `enforce(diff_path: str, runtime_path: str, output_path: str | None = None) -> int`
CI gate: blocks on HIGH risk, warns on UNKNOWN.

**Signature:**
```python
def enforce(diff_path: str, runtime_path: str, output_path: str | None = None) -> int:
```

**Returns:**
- 0 if no HIGH risk issues
- 1 if HIGH risk detected

---

### Patch Confidence

#### `compute_confidence(target_certainty: float, structural_safety: float, semantic_risk: float, complexity_penalty: float) -> float`
Score patch confidence by multiplying target × structural × semantic × complexity.

**Signature:**
```python
def compute_confidence(target_certainty: float, structural_safety: float, semantic_risk: float, complexity_penalty: float) -> float:
```

**Args:**
- `target_certainty`: Confidence in target identification (0.0 to 1.0)
- `structural_safety`: Safety of structural changes (0.0 to 1.0)
- `semantic_risk`: Semantic risk factor (0.0 to 1.0)
- `complexity_penalty`: Penalty for code complexity (0.0 to 1.0)

**Returns:**
Confidence score between 0.0 and 1.0

---

#### `classify_patch(confidence: float) -> str`
Classify patch confidence into categories.

**Signature:**
```python
def classify_patch(confidence: float) -> str:
```

**Returns:**
"HIGH", "MEDIUM", "LOW", or "UNKNOWN"

---

#### `get_target_certainty(...) -> float`
Calculate target certainty score.

#### `get_structural_safety(...) -> float`
Calculate structural safety score.

#### `get_semantic_risk(...) -> float`
Calculate semantic risk score.

#### `get_complexity_penalty(...) -> float`
Calculate complexity penalty.

---

### Report Generation

#### `generate_html(risk_json_path: str, output_path: str | None = None) -> str`
Generate static HTML report from risk JSON.

**Signature:**
```python
def generate_html(risk_json_path: str, output_path: str | None = None) -> str:
```

**Args:**
- `risk_json_path`: Path to risk report JSON
- `output_path`: Optional output HTML file path

**Returns:**
HTML content as string

---

### CLI Interface

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

---

### Convenience Functions (in `__init__.py`)

#### `extract_signatures(files) -> list[dict]`
Wrapper for `extract()`.

#### `compare_signatures(old_path, new_path) -> dict`
Wrapper for `compare()`.

#### `analyze_impact(sigs_path, calls_path, runtime_path=None) -> list[dict]`
Wrapper for `analyze()`.

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
    "kwarg": true
  }
]
```

### Call Sites JSON
```json
[
  {
    "caller": "src/caller.py:caller_func",
    "callee": "target_function",
    "line": 25,
    "args": ["arg1", "arg2"]
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
5. **Zero runtime samples**: `confidence(0)` returns 0.0, `exposure(0, N)` returns 0.0
6. **Single-element input**: Functions with no arguments, single call site
7. **Large input**: Projects with thousands of functions (must handle efficiently)
8. **Unicode in source**: Python files with non-ASCII characters
9. **Nested functions**: Inner functions are included with their names (no class/function context)
10. **Files with only classes**: No functions to extract (returns empty list)

---

## Performance & Constraints

### Performance Requirements
- Signature extraction: O(F × L) where F is number of files, L is average lines per file
- Signature comparison: O(S) where S is total number of signatures
- Memory: Should handle projects with 10,000+ functions within 512MB RAM

### Constraints
- Requires Python 3.9+ (uses `ast.unparse` for Python 3.9+)
- Runtime tracing adds overhead; use sampling in production (`trace_calls_prod.py`)
- External dependency: `libcst>=0.4.0` for CST-based patching
- No network access required
- No database dependencies

### Forbidden Patterns
- Do not use `eval()` or `exec()` on user code
- Do not modify source files during analysis (except patches which are explicit)
- Do not introduce circular imports within the package
