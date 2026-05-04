**ImpactGuard** — Lightweight API impact analyzer for Python projects.

<img src="logo.png" width="300px">

[![PyPI](https://img.shields.io/pypi/v/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Python](https://img.shields.io/pypi/pyversions/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Coverage](https://codecov.io/gh/daedalus/ImpactGuard/branch/main/graph/badge.svg)](https://codecov.io/gh/daedalus/ImpactGuard)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Features

- **Pipeline orchestrator** — Unified workflow connecting all components
- **Git commit comparison** — Compare any two git refs (commits, branches, tags)
- **AST-based signature extraction** — handles `async def`, decorators, type hints, `*args`, `**kwargs`
- **Semantic API diff** — classifies changes as breaking vs non-breaking
- **Call-site extraction** — finds all function/method calls in your codebase
- **Import-aware resolution** — resolves `from x import y`, aliases, and basic class context
- **Type-informed analysis** — uses type annotations and constructor inference
- **Runtime tracing** — optionally records actual calls during test runs
- **Risk assessment** — computes risk as S × E × C (severity × exposure × confidence)
- **HTML reporting** — generates static HTML reports from risk analysis
- **Patch suggestions** — provides fix suggestions with confidence scoring
- **CST-based patches** — preserves source formatting with libcst
- **Configuration system** — `impactguard.toml` for thresholds and settings

## Quick Start

```bash
# Install
pip install impactguard

# Compare two versions of your code (default pipeline mode)
impactguard old_version/ new_version/

# Compare two git commits directly
impactguard check-commits HEAD~1 HEAD

# Compare specific files between commits
impactguard check-commits HEAD~1 HEAD --files src/module.py src/utils.py

# Or use Python API
from impactguard import run_pipeline, quick_check, run_pipeline_git

result = run_pipeline("old/", "new/")
print(f"Breaking changes: {len(result['comparison']['breaking'])}")

# Compare git commits via API
result = run_pipeline_git("HEAD~1", "HEAD", files=["src/module.py"])
```

## CLI

**Pipeline mode (default):**
```bash
# Simplest usage - just provide old and new paths
impactguard old_version/ new_version/
impactguard old_version/ new_version/ runtime.json -o report.html

# Compare two git commits
impactguard check-commits HEAD~1 HEAD
impactguard check-commits main feature-branch --files src/core.py

# Using 'check' subcommand (equivalent, backwards compatible)
impactguard check old_version/ new_version/
```

**Individual commands (advanced):**
```bash
impactguard extract file1.py file2.py
impactguard compare old_sigs.json new_sigs.json
impactguard analyze signatures.json calls.json runtime.json
impactguard risk diff.txt runtime.json output.json
impactguard report risk.json output.html
impactguard trace install mypackage
impactguard trace dump runtime.json
```

## Python API

**Pipeline (recommended):**
```python
from impactguard import run_pipeline, quick_check, run_pipeline_git, ImpactGuard

# Full pipeline - extract, compare, analyze, risk, report
result = run_pipeline(
    old_path="src/",
    new_path="src/",
    runtime_path="runtime.json",  # optional
    output_path="report.html"      # optional
)

# Quick comparison only (extract + compare)
changes = quick_check("old/", "new/")
print(f"Breaking: {len(changes['comparison']['breaking'])}")

# Compare git commits
result = run_pipeline_git(
    old_ref="HEAD~1",
    new_ref="HEAD",
    files=["src/module.py"],  # optional: specific files only
)

# Use ImpactGuard class for more control
guard = ImpactGuard()
report = guard.check("old/", "new/", output="report.html")
```

**Individual components (advanced):**
```python
from impactguard import extract, compare, analyze_impact

# Extract signatures from Python files
signatures = extract(["src/module.py", "src/other.py"])

# Compare two signature snapshots
result = compare("old_sigs.json", "new_sigs.json")
print(f"Breaking changes: {len(result['breaking'])}")

# Analyze impact on call sites
issues = analyze_impact("signatures.json", "calls.json", "runtime.json")
```

## API Reference

### Pipeline (Recommended)
- `run_pipeline(old_path, new_path, runtime_path, output_path)` — Run full pipeline
- `quick_check(old_path, new_path)` — Quick extract + compare
- `run_pipeline_git(old_ref, new_ref, files, runtime_path, output_path)` — Compare two git commits
- `ImpactGuard` class — Full control with `check()`, `analyze()`, `compare()` methods

### Signature Extraction
- `extract(files)` — Extract function signatures from Python files
- `serialize_function(node, file)` — Convert AST node to signature dict

### Comparison
- `compare(old_path, new_path)` — Compare two signature snapshots
- `load(path)` — Load signatures from JSON file

### Impact Analysis
- `analyze(sigs_path, calls_path, runtime_path)` — Analyze impact on call sites
- `analyze_calls(signatures_file, calls_file, runtime_file)` — Type-aware impact analysis

### Risk Model
- `get_severity(change_type)` — Get severity score for change type
- `exposure(count, max_count)` — Calculate exposure score
- `confidence(samples, threshold)` — Calculate confidence score
- `classify(severity, count, max_count, samples)` — Classify risk level
- `compute_risk(severity, exposure_val, confidence_val)` — Compute risk score

### Reporting
- `generate_html(risk_json_path, output_path)` — Generate HTML report
- `enforce(diff_path, runtime_path, output_path)` — CI gate for risk enforcement

## How It Works

1. **Signature Extraction** — Parses Python AST to extract function signatures with full structural information (positional args, kwonly args, vararg/kwarg presence, defaults).

2. **API Diff** — Compares signature snapshots to detect removed functions, added required args, positional reordering, and other breaking changes.

3. **Call-Site Analysis** — Combines signature data with call-site extraction to predict which callers will break.

4. **Runtime Validation** — Instruments functions during test runs to record actual call patterns, then compares against new signatures.

5. **Pipeline Orchestrator** — Connects all components in one unified workflow (`run_pipeline()`).

6. **Git Integration** — Compare any two git commits directly (`run_pipeline_git()`).

## Install

```bash
pip install impactguard
```

## Development

```bash
git clone https://github.com/daedalus/ImpactGuard.git
cd ImpactGuard
pip install -e ".[test]"

# run tests
pytest

# format
ruff format src/ tests/

# lint
ruff check src/ tests/
prospector src/
semgrep --config=auto --severity=ERROR src/

# type check
mypy src/
```

## Quality Standards

ImpactGuard follows strict quality gates:
- **Ruff** — 0 issues (formatting + linting)
- **MyPy** — 0 errors (strict mode)
- **Prospector** — 0 warnings
- **Semgrep** — 0 findings
- **Coverage** — ≥80% (target)
- **Tests** — All passing

## Limitations

- Name collisions across files (uses file:function format)
- No full type inference — relies on annotations and simple constructor inference
- Dynamic dispatch, higher-order functions, and rebinding are not resolved
- Runtime tracing only captures code paths exercised by tests

## Future Directions

- Include class context (`ClassName.method`)
- Integrate with CI for enforcement
- Auto-generate changelogs from signature diffs
- Connect remaining components (analyze_module.py, patch_confidence.py, etc.)
- Boost test coverage from ~71% to 80%+
