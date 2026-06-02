# SPEC.md — ImpactGuard

## Purpose

ImpactGuard is a lightweight multi-language API impact analyzer. It tracks function signatures across commits, detects breaking changes, and analyzes call-site impact using both static and runtime techniques. The tool helps maintain API stability by providing actionable reports on how code changes affect downstream callers.

## Scope

### In Scope

- AST-based signature extraction from Python (`ast` stdlib) and tree-sitter grammars (TypeScript, JavaScript, Java, Kotlin, Go, Rust, Swift, C, C++, C#, Ruby, Haskell, Zig) with regex fallback
- Semantic comparison between signature snapshots (breaking vs non-breaking changes)
- Call-site extraction and impact analysis
- Type-aware module analysis with scope tracking
- Runtime call tracing during test execution (development tracer + production sampler)
- Risk assessment using S × E × C × λ model (severity × exposure × confidence × lambda)
- HTML, Markdown, and SARIF v2.1.0 report generation
- Patch confidence scoring (target certainty × structural safety × semantic risk × complexity penalty)
- CST-based patch generation that preserves source formatting (LibCST)
- Fix suggestion and automatic fix candidate generation
- Feedback loop for patch confidence calibration
- Semantic behavior analysis beyond signatures (async/sync, generators, exception contracts, side effects)
- Class hierarchy extraction and protocol cascade analysis
- KPI dashboard from risk reports
- CLI interface with 22 subcommands
- Git hook integration (pre-commit + post-commit) via pre-commit framework
- CI enforcement gate (blocks on HIGH / configurable UNKNOWN)
- Tagged release-history baselines
- Language-agnostic runtime normalization
- Offline operation (no network access required)

### Out of Scope

- Full type inference engine (relies on annotations and simple constructor inference)
- Dynamic dispatch resolution
- Higher-order function analysis
- Production-grade runtime tracing guarantee (a lightweight production sampler exists but is best-effort — not a core pipeline requirement)
- Runtime tracing and CST-based patch generation for non-Python languages (Python-only; other languages supply runtime data as JSON and receive text-based patch suggestions)

## Language Support

| Language | Extensions | Backend |
|---|---|---|
| Python | `.py` | `ast` (stdlib) |
| TypeScript | `.ts`, `.tsx` | tree-sitter / regex fallback |
| JavaScript | `.js`, `.mjs`, `.cjs` | tree-sitter / regex fallback |
| Java | `.java` | tree-sitter / regex fallback |
| Kotlin | `.kt`, `.kts` | tree-sitter / regex fallback |
| Go | `.go` | tree-sitter / regex fallback |
| Rust | `.rs` | tree-sitter / regex fallback |
| Swift | `.swift` | tree-sitter / regex fallback |
| C | `.c`, `.h` | tree-sitter / regex fallback |
| C++ | `.cpp`, `.hpp`, `.cc`, `.cxx`, `.hxx` | tree-sitter / regex fallback |
| C# | `.cs` | tree-sitter / regex fallback |
| Ruby | `.rb` | tree-sitter / regex fallback |
| Haskell | `.hs`, `.lhs` | tree-sitter / regex fallback |
| Zig | `.zig` | tree-sitter / regex fallback |

## Public API

### Package Overview

All public symbols are exported from `impactguard.__init__`. The `__all__` list contains ~90 entries organized into these categories:

### Pipeline (Recommended)

```python
from impactguard import (
    run_pipeline, run_pipeline_git, run_pipeline_diff,
    run_pipeline_diff_content, run_pipeline_commit,
    quick_check, ImpactGuard,
)

# Full pipeline: extract → compare → analyze → risk → report
result = run_pipeline(
    old_files=["src/"],
    new_files=["src/"],
    runtime_path="runtime.json",
    output_dir="report.html",
    suggest_patch=True,
    show_patch=True,
    generate_fixes=True,
    apply_safe_fixes=True,
)

# Quick comparison
result = quick_check("old/", "new/", runtime_path="runtime.json")

# Git commit comparison
result = run_pipeline_git(old_ref="HEAD~1", new_ref="HEAD")

# Diff-based pipeline
result = run_pipeline_diff(diff_path="changes.diff")

# Diff-content pipeline (from string)
result = run_pipeline_diff_content(diff_text="...")

# Single commit vs parent
result = run_pipeline_commit(commit_ref="HEAD")

# Class-based interface
guard = ImpactGuard()
result = guard.check("old/", "new/")
```

### Signature Extraction

```python
from impactguard import extract, serialize_function, extract_reexports

signatures = extract(files=["src/module.py"], strict=False)
# Returns list[dict] with keys: fqname, name, file, lineno, end_lineno,
#   positional, kwonly, vararg, kwarg, class_name, return_type,
#   decorators, is_async

# Language registry — multi-language dispatch
from impactguard import (
    LanguageExtractor, register_language, get_extractor,
    get_extractor_by_language, detect_language,
    list_languages, list_language_extensions,
)
```

### Comparison

```python
from impactguard import compare, load

result = compare(old_sigs, new_sigs)
# Returns {"breaking": [...], "nonbreaking": [...]}

sigs = load("signatures.json")  # dict keyed by fqname
```

### Impact Analysis

```python
from impactguard import (
    analyze, analyze_module, analyze_calls,
    build_call_graph, find_transitive_callers,
)

issues = analyze(sigs_path="sigs.json", calls_path="calls.json",
                 runtime_path="runtime.json")
# Returns list of impact issues

# Call graph
graph = build_call_graph(modules, signatures)
transitive = find_transitive_callers(function_fqname, graph)
```

### Risk Model (S × E × C × λ)

```python
from impactguard import (
    SEVERITY_SCORES, get_severity, exposure, confidence,
    classify, compute_risk,
    canonical_runtime_name, normalize_runtime_payload,
    load_runtime_observations,
)

severity = get_severity("REMOVED")       # 1.0
exp = exposure(count=42, max_count=100)  # min(1.0, log(1+count) / log(1+max_count))
conf = confidence(n=42, threshold=30)   # 0.0–1.0 based on sample size
risk = compute_risk(severity=1.0, exposure=0.85, confidence=0.95, lambda_=1.0)
label = classify(risk_score=0.72)       # "HIGH" / "MEDIUM" / "LOW" / "UNKNOWN"
```

### Reporting

```python
from impactguard import (
    generate_html, generate_html_from_file,
    generate_markdown, generate_markdown_from_file,
    generate_sarif, generate_sarif_from_file,
    enforce, enforce_report,
)

# HTML
html = generate_html(risk_data, issues=issues, output_path="report.html")

# Markdown (PR comments)
md = generate_markdown(risk_data)

# SARIF v2.1.0
sarif = generate_sarif(risk_data)
```

### Patch Generation

```python
from impactguard import patch_function, patch_call

# CST-based patching (LibCST)
result, error = patch_function(source_code, func_name, param_name)
result, error = patch_call(source_code, func_name, param_name)
```

### Patch Confidence

```python
from impactguard import (
    compute_confidence, classify_patch, classify_with_factors,
    get_target_certainty, get_structural_safety,
    get_semantic_risk, get_complexity_penalty,
)

confidence = compute_confidence(target_certainty=0.9, structural_safety=0.8,
                                 semantic_risk=0.7, complexity_penalty=0.95)
label = classify_patch(confidence_score=0.85)  # "HIGH" / "MEDIUM" / "LOW"
```

### Fix Generation

```python
from impactguard import (
    build_change_events, generate_fix_candidates,
    enrich_risk_with_fix_candidates, apply_safe_fixes,
)

events = build_change_events(comparison)
candidates = generate_fix_candidates(events)
enriched = enrich_risk_with_fix_candidates(risk_data, candidates)
applied = apply_safe_fixes(fix_candidates)
```

### Suggest Fixes

```python
from impactguard import suggest, enrich_with_fixes, get_line

suggestions = suggest(risk_item, report_data)
```

### Runtime Tracing

```python
from impactguard import (
    trace, install_tracer, dump_trace,
    install_tracer_prod, flush, should_sample,
)

# Development tracer (100%)
install_tracer(module, prefix="mypackage")

# Production sampler (1%)
install_tracer_prod(module, sample_rate=0.01)

# Dump collected data
dump_trace(".runtime_calls.json")
```

### Config

```python
from impactguard import (
    load_config, get_config, reload_config, validate_config, get_config_value,
)

load_config("impactguard.toml")
section_value = get_config_value("impactguard.analysis.include_private")
issues = validate_config()
```

### Baseline Management

```python
from impactguard import (
    save_baseline, load_baseline, compare_with_baseline, baseline_exists,
    save_tagged_baseline, load_tagged_baseline,
    list_baselines, compare_with_tagged_baseline, delete_tagged_baseline,
)

# Single baseline
save_baseline(files=["src/"], path=".impactguard_baseline.json")
result = compare_with_baseline(files=["src/"], baseline_path=".impactguard_baseline.json")

# Tagged release-history baselines
save_tagged_baseline(tag="v1.2.0", files=["src/"])
entries = list_baselines()
result = compare_with_tagged_baseline(tag_from="v1.0.0", files=["src/"])
delete_tagged_baseline(tag="v1.2.0")
```

### Semver

```python
from impactguard import suggest_semver, format_semver_recommendation

bump = suggest_semver(comparison)  # "major" | "minor" | "patch"
rec = format_semver_recommendation(comparison, current_version="1.2.3")
```

### Schema Validation

```python
from impactguard import (
    validate, validate_signatures_data, validate_calls_data,
    validate_runtime, validate_risk_report,
)

errors = validate_signatures_data(signatures_data)
errors = validate_calls_data(calls_data)
errors = validate_runtime(runtime_data)
errors = validate_risk_report(report_data)
```

### Class Hierarchy / Protocol Cascade

```python
from impactguard import (
    extract_class_hierarchy, find_implementations, get_cascade_changes,
)

hierarchy = extract_class_hierarchy(signatures)
implementations = find_implementations(protocol_fqname, signatures)
cascade = get_cascade_changes(changed_class, signatures)
```

### Feedback Loop

```python
from impactguard import (
    record_outcome, load_outcomes, get_feedback_stats,
    compute_calibrated_weights, apply_weights_to_config,
)

record_outcome(patch_id="abc123", accepted=True)
stats = get_feedback_stats(feedback_path=".impactguard_feedback.json")
weights = compute_calibrated_weights(outcomes)
apply_weights_to_config(weights, "impactguard.toml")
```

### KPI Dashboard

```python
from impactguard import compute_kpis, format_kpi_text

kpis = compute_kpis(risk_report_data, feedback_outcomes=feedback_data)
print(format_kpi_text(kpis))
```

### Semantic Behavior Analysis

```python
from impactguard import (
    analyze_behavior, compare_behavior, SEMANTIC_SEVERITY,
)

traits = analyze_behavior(files=["src/module.py"])
diff = compare_behavior(old_traits, new_traits)
```

### Logging

```python
from impactguard import get_logger, configure_logging

configure_logging(level="DEBUG", log_file="impactguard.log")
logger = get_logger(__name__)
```

## CLI Reference

### Entry Points

| Console script | Target |
|---|---|
| `impactguard` | `impactguard.__main__:main` |
| `impactguard-check-staged` | `impactguard.__main__:check_staged` |
| `impactguard-post-commit-hook` | `impactguard.__main__:post_commit_hook` |

### Subcommands

| Subcommand | Description |
|---|---|
| `extract` | Extract function signatures from source files |
| `compare` | Compare signature snapshots or source files |
| `analyze` | Analyze impact on call sites |
| `risk` | Run risk analysis pipeline |
| `report` | Generate HTML report from risk JSON |
| `report-sarif` | Generate SARIF v2.1.0 log from risk report JSON |
| `report-markdown` | Generate markdown PR comment from risk report JSON |
| `enforce` | Enforce gate — block on HIGH risk |
| `suggest` | Generate fix suggestions from risk report |
| `patch` | Generate CST-based patches for source files |
| `extract-calls` | Extract call sites from source files |
| `trace` | Runtime tracing (`install`, `dump`) |
| `check` | Run full pipeline (default mode) |
| `check-diff` | Run full pipeline on a unified diff/patch file |
| `check-commit` | Run full pipeline on a single commit vs parent |
| `check-commits` | Compare two git commits with full pipeline |
| `install-hooks` | Install git hooks for ImpactGuard |
| `generate-changelog` | Generate changelog from signature diffs |
| `baseline` | Manage baselines (`save`, `status`, `compare`) |
| `semver` | Suggest semver bump from signature snapshots |
| `feedback` | Manage patch-outcome feedback (`record`, `stats`, `calibrate`) |
| `history` | Manage tagged release-history baselines (`list`, `save`, `compare`, `delete`) |
| `validate-config` | Validate `impactguard.toml` configuration |
| `kpi` | Compute KPI dashboard from risk report JSON |
| `analyze-behavior` | Detect semantic/behavioral changes between source files |

### Pipeline Mode

```bash
# Default pipeline mode (auto-detected when args are not a subcommand name)
impactguard old/ new/ [runtime] [output]

# Or explicit
impactguard check old/ new/ [runtime] [output]
impactguard check old/ new/ --watch
impactguard check old/ new/ --report-sarif results.sarif
impactguard check old/ new/ --suggest-patch --show-patch
```

### Common Flags

All `check-*` commands accept:

- `--runtime PATH` — Runtime data JSON
- `--suggest-patch` — Generate patch files
- `--show-patch` — Display patched content inline
- `--no-generate-fixes` — Disable fix-candidate generation
- `--apply-safe-fixes` — Apply high-confidence CST fixes automatically
- `--strict-extraction` — Treat parse errors as fatal
- `--report-sarif PATH` — Write SARIF v2.1.0 report

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
      {"name": "arg2", "has_default": true, "type": "str"}
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
    "positional": [],
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

### Call Sites JSON

```python
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

Canonical list format:
```json
[
  {"function": "src/module.py:function_name", "count": 42}
]
```

Additional accepted formats (normalized automatically):

| Format | Example |
|---|---|
| Single observation | `{"function": "pkg/module.py:fn", "count": 4}` |
| Map-style | `{"pkg::fn": 12, "pkg::other": 3}` |
| Envelope | `{"runtime": [...]}` |

Separator normalization: `:`, `::`, `/`, `#` are all treated equivalently.

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

- `risk`: `"HIGH"` / `"MEDIUM"` / `"LOW"` / `"UNKNOWN"`
- `transitive`: `true` when this entry represents an indirect caller (always `"LOW"`)
- `lambda`: sensitivity multiplier (default `1.0`)

### Semver Recommendation JSON

```json
{
  "bump": "major",
  "reason": "3 breaking change(s) detected",
  "breaking_count": 3,
  "nonbreaking_count": 1,
  "next_version": "2.0.0"
}
```

### Baseline JSON

```json
{
  "signatures": [...],
  "metadata": {
    "saved_at": "2026-01-01T00:00:00Z",
    "files_count": 12
  }
}
```

### SARIF v2.1.0

Generated by `sarif.py`. Produces a standard SARIF log with:

- Tool: `ImpactGuard` with version
- Rules indexed by change type
- Results with level mapping: `HIGH` → `error`, `MEDIUM` → `warning`, `LOW` → `note`, `UNKNOWN` → `none`
- Locations with file URI, line, and column

### Pipeline Result JSON

```json
{
  "comparison": {"breaking": [...], "nonbreaking": [...]},
  "semver": {"bump": "major", ...},
  "risk": [...],
  "analysis_status": {
    "status": "complete",
    "counters": {
      "parse_failures": 0,
      "skipped_files": 0,
      "fallback_used": 0,
      "call_extraction_failures": 0,
      "runtime_data_issues": 0
    },
    "runtime": {"state": "available"}
  },
  "gate": {"blocked": false, "reasons": []},
  "report_html": "<!DOCTYPE html...>",
  "fixes": [...],
  "patches": {"func_name": {"type": "...", "file": "..."}}
}
```

## Configuration (`impactguard.toml`)

```toml
[impactguard]
# General settings

[impactguard.analysis]
include_private = false
strict = false

[impactguard.risk]
lambda = 1.0
block_unknown = false

[impactguard.logging]
level = "WARNING"
format = "%(levelname)s:%(name)s:%(message)s"
log_file = ""
```

Validate with: `impactguard validate-config`

## CLI Console Scripts

| Script | Purpose |
|---|---|
| `impactguard-check-staged` | Pre-commit hook — runs pipeline on staged diff |
| `impactguard-post-commit-hook` | Post-commit hook — extracts signatures from tracked files |

## Edge Cases

1. **Empty input files list**: `extract([])` returns `[]`
2. **Syntax errors**: Files with parse errors emit a `SyntaxWarning` and are skipped. Pass `strict=True` / `--strict` to turn skips into hard errors (recommended for CI).
3. **Missing JSON files**: `load()` and `compare()` handle gracefully
4. **Empty signature snapshots**: Comparison handles empty old or new
5. **Zero runtime samples**: `confidence(0)` → `0.0`, `exposure(0, N)` → `0.0`
6. **Single-element/empty input**: Functions with no arguments, single call site
7. **Large input**: Projects with thousands of functions (handled efficiently)
8. **Unicode in source**: Supported
9. **Nested functions**: Included with their names (no class context for nesting)
10. **Class methods**: Include class context in `fqname` (`ClassName.method`) and `class_name` field
11. **Files with only classes**: No functions to extract → empty list
12. **Private symbols**: Functions whose leaf name starts with `_` excluded from comparison by default. Pass `include_private=True` to `compare()` or set `[impactguard.analysis] include_private = true`.
13. **Missing baseline**: `compare_with_baseline()` raises `FileNotFoundError`
14. **Non-semver current_version**: `_increment()` appends `-next` instead of failing
15. **FQN basename collision**: Without `base_path`, fqnames use file basename. For monorepos, pass `base_path=<project_root>` to `extract()` so fqnames are project-relative paths.
16. **Tree-sitter package missing**: Falls back to regex extraction with `UserWarning`
17. **Unknown file extension**: File is skipped with a warning message
18. **`--pipe` with no stdin**: Exits with error message
19. **`--watch` with no changes**: Blocks until file change detected
20. **Feedback calibration without data**: Requires ≥ 5 outcomes per category

## Performance & Constraints

### Performance

- Signature extraction: O(F × L) where F = files, L = average lines per file
- Signature comparison: O(S) where S = total signatures
- Memory: handle 10,000+ functions in 512MB RAM

### Constraints

- Python 3.11+ (uses `ast` features + `ast.unparse`)
- Tree-sitter backends require `tree-sitter>=0.23` + grammar packages (`pip install "impactguard[languages]"`)
- CST patching: `libcst>=0.4.0`
- Git hooks: `pre-commit>=4.6.0`, `pyyaml>=6.0`
- No network access required
- No database dependencies

### Forbidden Patterns

- No `eval()` or `exec()` on user code
- No source file modification during analysis (patches are explicit)
- No circular imports within the package
- Top-level imports only (lazy imports used only in CLI for performance)

## Invariants

### All Modules

- Type annotations on all public functions (mypy strict mode compliant)
- Ruff format clean (0 issues)
- Ruff check clean (0 issues)
- MyPy clean (0 errors in strict mode)

### Signature Extraction

- Output sorted by `fqname`
- Handles `def` and `async def`
- Skips parse failures with `SyntaxWarning` (use `--strict` for CI)
- Language detected from file extension (override with `--language`)

### Risk Model

- S × E × C × λ scoring with configurable lambda
- Lambda defaults to `1.0`; `>1` increases sensitivity, `<1` decreases
- `UNKNOWN` risk requires runtime call-count data above confidence threshold
- Coverage requirement: ≥ 80%
- All edge cases have corresponding tests
