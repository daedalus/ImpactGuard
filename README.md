**ImpactGuard** — Lightweight API impact analyzer for Python projects.

[![PyPI](https://img.shields.io/pypi/v/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Python](https://img.shields.io/pypi/pyversions/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Coverage](https://codecov.io/gh/daedalus/ImpactGuard/branch/main/graph/badge.svg)](https://codecov.io/gh/daedalus/ImpactGuard)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Features

- **Pipeline orchestrator** — connects all components in one unified workflow
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

# Or use Python API
from impactguard import run_pipeline, quick_check

result = run_pipeline("old/", "new/")
print(f"Breaking changes: {len(result['comparison']['breaking'])}")
```

## Install

```bash
pip install impactguard
```

## Usage

**Python API (recommended):**
```python
from impactguard import run_pipeline, quick_check, ImpactGuard

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

## CLI

**Pipeline mode (default):**
```bash
# Simplest usage - just provide old and new paths
impactguard old_version/ new_version/
impactguard old_version/ new_version/ runtime.json -o report.html

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

## API

### Pipeline (Recommended)
- `run_pipeline(old_path, new_path, runtime_path, output_path)` — Run full pipeline
- `quick_check(old_path, new_path)` — Quick extract + compare
- `ImpactGuard` class — Full control with `check()`, `extract()`, `compare()` methods

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

## Post-Commit Hook

The repo includes a `post-commit` hook that:
- Runs after every commit
- Updates `.signatures.txt` if Python files changed
- Creates a follow-up commit only if signatures actually changed
- Uses `SKIP_SIGNATURE_HOOK=1` to prevent infinite recursion

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

## Limitations

- Name collisions across files (uses file:function format)
- No full type inference — relies on annotations and simple constructor inference
- Dynamic dispatch, higher-order functions, and rebinding are not resolved
- Runtime tracing only captures code paths exercised by tests

## Future Directions

- Include class context (`ClassName.method`)
- Detect breaking vs non-breaking API changes automatically
- Compare signatures across commits
- Integrate with CI for enforcement
- Auto-generate changelogs from signature diffs
