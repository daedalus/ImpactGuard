# **ImpactGuard** — Lightweight API impact analyzer for Python projects

<img src="logo.png" width="300px">

[![PyPI](https://img.shields.io/pypi/v/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Python](https://img.shields.io/pypi/pyversions/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Actions status](https://github.com/daedalus/impactguard/workflows/CI/badge.svg)](https://github.com/daedalus/impactguard/actions)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/daedalus/ImpactGuard)

## Overview

ImpactGuard is a lightweight API impact analyzer for Python projects designed to maintain API stability by tracking function signatures across commits, detecting breaking changes, and analyzing call-site impact using both static and runtime techniques.

It provides a quantitative risk framework to help developers understand the consequences of code changes before they are merged.

### Core Capabilities

- **AST-based Extraction**: Automatically extracts function signatures, including `async def`, decorators, and type hints
- **Semantic API Diffing**: Classifies changes into a taxonomy of breaking (e.g., removing positional arguments) vs. non-breaking (e.g., adding optional keyword-only arguments)
- **Impact Analysis**: Correlates signature changes with static call-site extraction and optional runtime tracing to identify affected downstream code
- **Risk Assessment**: Quantifies the danger of a change using the **S × E × C** (Severity × Exposure × Confidence) model
- **Automated Remediation**: Generates format-preserving patches using LibCST to fix broken call sites

### System Components

| Component | Module | Description |
|-----------|--------|-------------|
| Signature Extraction | `extract_signatures.py` | AST-based extraction of function metadata |
| Signature Comparison | `compare_signatures.py` | Semantic diffing of API changes |
| Call-Site Analysis | `extract_calls.py`, `analyze_module.py` | Static call-site extraction and resolution |
| Impact Analysis | `impact_analysis.py` | Correlates changes with call sites |
| Risk Model | `risk_model.py` | S × E × C risk scoring |
| Risk Gate | `risk_gate.py`, `enforce_gate.py` | CI enforcement engine |
| Runtime Tracing | `trace_calls.py`, `trace_calls_prod.py` | Development and production tracers |
| Patch Generation | `cst_patch.py`, `patch_generator.py` | Format-preserving automated fixes |
| Reporting | `generate_report.py` | Static HTML report generation |
| CLI | `cli.py` | Command-line interface |

---

## Language Support

| Language | Extensions | Extraction Backend | Signature Extraction | Call-Site Extraction | Type Annotations | Optional Dependency | Status |
|----------|------------|--------------------|:--------------------:|:--------------------:|:----------------:|---------------------|--------|
| **Python** | `.py` | `ast` (stdlib) | Yes | Yes | Yes | — | Stable |
| **TypeScript** | `.ts`, `.tsx` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |

> **Note:** The TypeScript tree-sitter backend requires `tree-sitter>=0.23` and `tree-sitter-typescript>=0.23`, installed via `pip install "impactguard[languages]"`. When those packages are absent, ImpactGuard automatically falls back to regex-based extraction and emits a `UserWarning`.
>
> To add support for a new language, implement the [`LanguageExtractor`](src/impactguard/languages/base.py) protocol and register the extractor with [`register()`](src/impactguard/languages/registry.py).

---

## Quick Start

### Installation

**Prerequisites:**

- Python 3.11 or higher
- Dependencies: `libcst` for concrete syntax tree manipulations

```bash
# Install from PyPI
pip install impactguard

# Or install for development
git clone https://github.com/daedalus/ImpactGuard.git
cd ImpactGuard
pip install -e ".[test]"
```

### Project Layout

| Path | Description |
|------|-------------|
| `src/impactguard/` | Core package containing the analysis logic, risk model, and CLI |
| `extract_signatures.py` | Utility for extracting function metadata into JSON/Text |
| `extract_calls.py` | AST-based call site extractor |
| `impact_analysis.py` | Logic for correlating signatures with call sites |
| `risk_gate.py` | The CI-ready enforcement engine |
| `trace_calls.py` | Runtime instrumentation for capturing live execution data |
| `SPEC.md` | Technical specification and public API |

The full pipeline can be executed using the `impactguard` CLI:

```bash
# 1. Extract signatures and calls
impactguard extract $(git ls-files '*.py') > .signatures.json
impactguard extract-calls $(git ls-files '*.py') > .calls.json

# 2. Capture runtime exposure (optional)
impactguard trace dump .runtime_calls.json

# 3. Compare and analyze risk
impactguard risk diff.txt .runtime_calls.json report.json

# 4. Generate the report
impactguard report report.json api_report.html
```

Or use the Python API:
```python
from impactguard import run_pipeline

result = run_pipeline(
    old_path="old_version/",
    new_path="new_version/",
    runtime_path="runtime.json",  # optional
    output_path="report.html"      # optional
)
print(f"Breaking changes: {len(result['comparison']['breaking'])}")
```

---

## Core Analysis Pipeline

ImpactGuard operates as a **pipe-and-filter architecture** where artifacts from one stage inform the next.

### 1. Signature Extraction

The first stage involves deep inspection of Python source files using the `ast` module. The `extract` function walks the Abstract Syntax Tree to identify all function and method definitions. It generates a "fingerprint" for every callable, including its Fully Qualified Name (FQN), parameters, defaults, and decorators.

- **Key Component:** `extract_signatures.py`
- **Output:** `.signatures.json`
- **Role:** Establishes the baseline of the API surface

### 2. Signature Comparison

Once two snapshots of a codebase exist (e.g., `HEAD` vs `main`), the `compare` utility performs a semantic diff. Unlike a standard text-based diff, this stage understands Python's parameter rules. It categorizes changes into **Breaking** (e.g., removing a parameter, reordering positional arguments) and **Non-breaking** (e.g., adding an optional keyword argument).

- **Key Component:** `compare_signatures.py`
- **Output:** A structured list of semantic changes
- **Role:** Identifies exactly how the API contract has evolved

### 3. Call-Site and Module Analysis

To understand the "blast radius" of a change, ImpactGuard must find where the modified functions are actually used. This is achieved through two complementary approaches:

1. **Lightweight Extraction:** Rapidly finding call nodes in the AST
2. **Deep Module Analysis:** Tracking imports and assignments to resolve method calls to their actual definitions (FQN resolution)

- **Key Components:** `extract_calls.py` and `analyze_module.py`
- **Output:** `.calls.json`
- **Role:** Maps the internal dependency graph of the codebase

### 4. Impact Analysis

The final stage of the core pipeline, `analyze`, correlates the detected API changes with the discovered call sites. It validates whether the arguments passed at a specific call site still satisfy the requirements of the new function signature. If runtime data is available, it is integrated here to provide context on how often a specific impacted path is actually executed.

- **Key Component:** `impact_analysis.py`
- **Input:** Signature diffs, call-site data, and optional runtime traces
- **Role:** Pinpoints exactly which lines of code are broken by a change

---

### Examples of Changes

#### Non-Breaking Changes
These changes do NOT break existing callers:

- **Adding optional parameters**: `def foo(a, b=1)` → `def foo(a, b=1, c=0)` (no callers need to change)
- **Adding keyword-only arguments**: `def foo(a)` → `def foo(a, *, debug=False)` (existing callers unaffected)
- **Adding new functions/classes**: Entirely new APIs that don't affect existing code
- **Adding `*args` or `**kwargs`**: `def foo(a)` → `def foo(a, *args)` (backward compatible)

#### Breaking Changes
These changes WILL break existing callers:

- **Removing required parameters**: `def foo(a, b)` → `def foo(a)` (callers passing `b` will fail)
- **Reordering positional arguments**: `def foo(a, b)` → `def foo(b, a)` (callers' positional args swap)
- **Removing functions/methods**: Any callable that's removed entirely
- **Changing parameter types**: `def foo(a: int)` → `def foo(a: str)` (type safety breaks)

---

## Risk Model and Enforcement

The **Risk Model and Enforcement** subsystem is the decision-making engine of ImpactGuard. It transforms raw signature changes and runtime telemetry into actionable risk levels (`HIGH`, `MEDIUM`, `LOW`, or `UNKNOWN`). These levels are then used to automatically block or permit CI/CD pipelines based on the potential impact on consumers.

### The S × E × C Risk Framework

The core logic resides in `risk_model.py`. It quantifies risk by evaluating three distinct dimensions:

| Component | Code Entity | Description |
|-----------|-------------|-------------|
| **Severity (S)** | `get_severity()` | Score (0.1 to 1.0) based on change type (e.g., `REMOVED` = 1.0, `ADDED` = 0.1) |
| **Exposure (E)** | `exposure()` | Logarithmic scale mapping call counts to a 0.0-1.0 range |
| **Confidence (C)** | `confidence()` | Measures data reliability based on sample size against a threshold |
| **Classification** | `classify()` | Uses a decision tree to assign the final risk label |

**Exposure Calculation:** `min(1.0, log(1 + count) / log(1 + max_count))`

### CI Enforcement

The risk assessment is operationalized through `risk_gate.py` and `enforce_gate.py`:

1. **Risk Gate Execution**: `risk_gate.py` contains the `run()` function which parses the diff and runtime data to generate a comprehensive `report.json`
2. **Gate Enforcement**: `enforce_gate.py` consumes this report:
   - If any item is flagged as `HIGH` risk → exits with code `1` (blocks build)
   - If `UNKNOWN` risks are detected → issues a warning but allows build (exit code `0`)

---

## Runtime Tracing

The **Runtime Tracing** subsystem provides dynamic analysis capabilities to complement ImpactGuard's static analysis pipeline. By observing actual execution patterns, the system captures "Exposure" data which is used by the `risk_model.py` to weight the impact of breaking changes.

### Development Tracer (`trace_calls.py`)

Designed for test suites and local execution where performance is less critical than data accuracy. It uses an `@trace` decorator to capture not just call counts, but also signature metadata like argument counts and keyword argument names.

- **Key Mechanism:** Uses `inspect.signature(func).bind_partial(*args, **kwargs)` to validate and record invocations
- **Integration:** Commonly used via `install_tracer()` in test fixtures

### Production Sampler (`trace_calls_prod.py`)

Optimized for minimal overhead in live environments. It employs a probabilistic sampling strategy (default 1%) to capture a representative subset of traffic.

- **Sampling Logic:** Only records data if `random.random() < SAMPLE_RATE`
- **Background Flushing:** Periodically flushes captured counts to disk (default every 10 seconds)

| Feature | Development Tracer | Production Sampler |
|---------|-------------------|-------------------|
| **Primary Goal** | Deep visibility / Test coverage | Low overhead monitoring |
| **Data Captured** | Counts + Arg structure | Call Counts only |
| **Sampling** | 100% (No sampling) | 1% (Adjustable) |
| **Storage Trigger** | Manual `dump()` call | Periodic `flush()` (10s interval) |

---

## Patch Generation and Remediation

The Patch Generation subsystem transforms identified impact risks into actionable code fixes. It provides a multi-tiered approach to remediation, ranging from high-level suggestions to precise, format-preserving code transformations using Concrete Syntax Trees (CST).

### Patch Suggestion and Diff-Based Patching

The system first generates high-level suggestions based on the nature of the breaking change. For simple scenarios, it employs a naive line-based patching strategy using Python's `difflib`.

- **Logic Location**: `suggest_fixes.py` analyzes issues to recommend actions
- **Naive Patching**: `patch_generator.py` uses `difflib.unified_diff` for simple string replacement

### CST-Based Patching (`cst_patch.py`)

To handle complex code structures, ImpactGuard utilizes `LibCST`. Unlike standard AST, a Concrete Syntax Tree preserves formatting, comments, and whitespace.

- **Transformers**: Uses `AddDefaultTransformer` to modify function signatures and `FixCallTransformer` to inject missing arguments into call sites
- **Safety**: Gracefully falls back to simpler methods if `libcst` is not installed

### Patch Confidence Scoring

Every generated patch is assigned a confidence score (0.0 to 1.0) to determine if it can be auto-applied:

1. **Target Certainty (T)**: How sure we are that we found the correct line
2. **Structural Safety (S)**: Is the change a simple default addition or a risky positional reorder?
3. **Semantic Risk (R)**: Does the change affect required parameters?
4. **Complexity Penalty (C)**: Is the code heavily decorated or nested?

---

## CLI Reference

The `impactguard` command-line tool is the primary entry point for developers and automation scripts.

### Pipeline Mode (Recommended)

```bash
# Compare two versions of your code
impactguard old_version/ new_version/

# Compare two git commits directly
impactguard check-commits HEAD~1 HEAD

# Compare specific files between commits
impactguard check-commits HEAD~1 HEAD --files src/module.py src/utils.py
```

### Individual Commands (Advanced)

```bash
impactguard extract file1.py file2.py
impactguard compare old_sigs.json new_sigs.json
impactguard analyze signatures.json calls.json runtime.json
impactguard risk diff.txt runtime.json output.json
impactguard report risk.json output.html
impactguard trace install mypackage
impactguard trace dump runtime.json
impactguard install-hooks . --both  # Install git hooks
```

### Git Hooks Installation

```bash
# Install both pre-commit and post-commit hooks
impactguard install-hooks .

# Install only pre-commit hook
impactguard install-hooks . --pre

# Install only post-commit hook (updates signature tracking)
impactguard install-hooks . --post
```

---

## Python Library API

The `impactguard` package exports its core functionality for programmatic integration.

### Pipeline (Recommended)

```python
from impactguard import run_pipeline, quick_check, run_pipeline_git, ImpactGuard

# Full pipeline - extract, compare, analyze, risk, report
result = run_pipeline(
    old_path="src/",
    new_path="src/",
    runtime_path="runtime.json",
    output_path="report.html"
)

# Quick comparison only (extract + compare)
changes = quick_check("old/", "new/")
print(f"Breaking: {len(changes['comparison']['breaking'])}")

# Compare git commits
result = run_pipeline_git(
    old_ref="HEAD~1",
    new_ref="HEAD",
    files=["src/module.py"]
)

# Use ImpactGuard class for more control
guard = ImpactGuard()
report = guard.check("old/", "new/", output="report.html")
```

### Individual Components (Advanced)

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

---

## Git Hooks and Workflow Integration

ImpactGuard is designed to be deeply integrated into the standard Git development workflow.

### Post-Commit Hook

This hook ensures that every commit is accompanied by updated signature tracking. It includes a `SKIP_SIGNATURE_HOOK` environment variable check to prevent infinite recursion when the hook itself creates a new commit.

### Pre-Push Hook

This acts as the final safety gate. It typically runs `compare_signatures.py` to evaluate the delta between the local branch and `origin/master`. If the risk gate detects high-risk breaking changes without appropriate mitigations, the push is blocked.

---

## CI/CD and Release Infrastructure

### CI Pipeline

The CI pipeline is defined in `.github/workflows/ci.yml` and executes on all pushes and pull requests targeting the `master` branch. It consists of three parallel jobs:

- **Test Matrix:** Executes `pytest` across Python versions 3.11, 3.12, and 3.13
- **Static Analysis (Linting):** Runs `ruff`, `prospector`, `semgrep`, and `mypy`
- **Build Verification:** Ensures the package can be successfully built via `twine check`

### Packaging and Release

ImpactGuard uses modern Python packaging standards with `hatchling` as the build backend.

**Dependency Groups:**
| Group | Purpose | Key Tools |
|-------|---------|-----------|
| `dev` | General development | `hatch`, `pip-api` |
| `test` | Automated testing | `pytest`, `hypothesis` |
| `lint` | Static analysis | `ruff`, `mypy`, `semgrep` |

**Release Automation:**

- **Version Management:** Uses `bumpversion` to maintain consistency across `pyproject.toml` and `src/impactguard/__init__.py`
- **Automated Publishing:** The `pypi-publish.yml` workflow triggers on GitHub Release events to build and publish to PyPI using Trusted Publishers (OIDC)

---

## Testing

The ImpactGuard test suite ensures the reliability of the signature extraction pipeline, the accuracy of the risk model, and the stability of the CLI. The project maintains a strict quality gate, requiring a minimum of 80% code coverage.

### Test Architecture

1. **Unit Tests**: Isolated testing of individual modules (extraction, comparison, patching)
2. **Integration Tests**: End-to-end CLI flows and public API surface validation
3. **Coverage Enforcement**: Automated checks to ensure the codebase meets the 80% threshold

### Test Fixtures

| Fixture | Description |
|---------|-------------|
| `sample_signature_data` | Returns a list of dictionaries representing serialized function signatures |
| `sample_signatures_file` | Creates a temporary `.json` file containing signature data |
| `sample_python_file` | Generates a temporary `.py` file with functions and classes |
| `runtime_data_file` | Provides a temporary JSON file simulating tracer output |

---

## How It Works

1. **Signature Extraction** — Parses Python AST to extract function signatures with full structural information
2. **API Diff** — Compares signature snapshots to detect removed functions, added required args, positional reordering, and other breaking changes
3. **Call-Site Analysis** — Combines signature data with call-site extraction to predict which callers will break
4. **Runtime Validation** — Instruments functions during test runs to record actual call patterns
5. **Pipeline Orchestrator** — Connects all components in one unified workflow (`run_pipeline()`)
6. **Git Integration** — Compare any two git commits directly (`run_pipeline_git()`)

---

## Intermediate Artifacts

The pipeline relies on standardized JSON schemas to pass data between filters:

| Artifact | Producer | Consumer | Description |
|----------|-----------|----------|-------------|
| `.signatures.json` | `extract_signatures.py` | `compare_signatures.py`, `impact_analysis.py` | Function metadata including arguments, defaults, and line numbers |
| `.calls.json` | `extract_calls.py` | `impact_analysis.py` | Static call sites mapped by caller and callee |
| `.runtime_calls.json` | `trace_calls.py` | `impact_analysis.py`, `risk_gate.py` | Frequency and argument data from execution |
| `report.json` | `risk_gate.py` | `generate_report.py`, `suggest_fixes.py` | Final risk classifications (HIGH/MEDIUM/LOW) |

---

## Self-Testing (Dogfooding)

ImpactGuard has been **tested on itself** to validate its own API changes:

```bash
# Extract signatures from own codebase
$ impactguard extract src/impactguard/*.py
✓ Extracted 98 function signatures

# Detect non-breaking change (added optional parameter)
✓ Correctly classified as "Non-breaking changes: 1"

# Detect breaking change (removed required parameter)
✓ Correctly classified as "Breaking changes: 1"

# Run full pipeline on itself
$ impactguard check-commits HEAD~5 HEAD
✓ Pipeline orchestrator completed successfully
✓ Generated HTML report with risk analysis
```

---

## Quality Standards

ImpactGuard follows strict quality gates:

- **Ruff** — 0 issues (formatting + linting)
- **MyPy** — 0 errors (strict mode)
- **Prospector** — 0 warnings
- **Semgrep** — 0 findings
- **Coverage** — ≥80% (target)
- **Tests** — All passing

---

## Glossary

### Core Concepts

- **Signature**: A structured representation of a Python function's interface, including positional arguments, keyword-only arguments, and variadic arguments
- **FQName (Fully Qualified Name)**: A unique identifier in `file_path:function_name` format (e.g., `src/auth.py:login`)
- **Breaking Change**: A modification that prevents existing callers from executing correctly (e.g., `REMOVED`, `REQUIRED_POSITIONAL_ADDED`, `POSITIONAL_REORDER`)

### Risk Framework (S × E × C)

- **Severity (S)**: The technical impact of the change type (0.1 to 1.0)
- **Exposure (E)**: How often the function is called, calculated logarithmically
- **Confidence (C)**: The reliability of runtime data based on sample size

### Patching

- **CST (Concrete Syntax Tree)**: Unlike AST, preserves formatting, comments, and whitespace
- **Patch Confidence**: A score from 0.0 to 1.0 representing the likelihood that an automated fix is correct

---

## Direct Competitors (Python API analysis space)

The table below compares ImpactGuard against the tools most commonly used for Python API change management, static analysis, and release automation. As of 2026-05, to our knowledge:

| Feature | **ImpactGuard** | **griffe** | **python-semantic-release** | **commitizen** | **pyright / mypy** |
|---|---|---|---|---|---|
| AST-based signature extraction | ✅ Full (positional, kwonly, vararg, return type, decorators, async) | ✅ Full | ❌ | ❌ | ✅ (internal only) |
| Breaking-change detection | ✅ Semantic diff (added / removed / modified) | ✅ | ❌ Code-unaware | ❌ Code-unaware | ⚠️ Type errors only |
| Call-site impact analysis | ✅ Static call-site traversal | ❌ | ❌ | ❌ | ❌ |
| Runtime call tracing | ✅ (test + production sampler) | ❌ | ❌ | ❌ | ❌ |
| Risk scoring (S × E × C model) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Transitive impact tracking | ✅ | ❌ | ❌ | ❌ | ❌ |
| Semver bump recommendation | ✅ From code diff | ⚠️ Partial (griffe-diff) | ✅ From commit msgs | ✅ From commit msgs | ❌ |
| Changelog generation | ✅ From signature diff | ⚠️ Via mkdocs plugin | ✅ From commit msgs | ✅ From commit msgs | ❌ |
| HTML report | ✅ | ❌ | ❌ | ❌ | ❌ |
| Patch generation (CST-based) | ✅ Formatting-preserving | ❌ | ❌ | ❌ | ⚠️ Quickfix only |
| Patch confidence scoring | ✅ | ❌ | ❌ | ❌ | ❌ |
| Baseline management | ✅ Save / compare / diff | ⚠️ Via snapshots | ❌ | ❌ | ❌ |
| CI enforcement gate | ✅ Blocks on HIGH / UNKNOWN | ❌ | ✅ (release gate) | ✅ (lint gate) | ✅ (type gate) |
| Git hook integration | ✅ Pre + post commit | ❌ | ❌ | ✅ | ❌ |
| Config file (TOML) | ✅ `impactguard.toml` | ✅ | ✅ | ✅ | ✅ |
| Watch mode (live re-run) | ✅ `--watch` | ❌ | ❌ | ❌ | ✅ |
| No network required | ✅ | ✅ | ❌ (PyPI / git) | ❌ (git) | ✅ |

### Ecosystem-adjacent tools

| Tool | Domain | Overlap with ImpactGuard | What ImpactGuard adds |
|---|---|---|---|
| **griffe** | Python API docs + diff | Closest alternative — extracts signatures, detects breaking changes | Call-site analysis, runtime tracing, risk model, patch generation |
| **python-semantic-release** | Automated releases + semver | Semver bumps from conventional commits | Code-level proof, not just commit message convention |
| **commitizen** | Conventional commits + changelog | Changelog generation, git hooks | Actual API-level analysis and enforcement |
| **bump2version / bumpversion** | Version string management | Version bumping | All analysis features |
| **mypy / pyright** | Static type checking | Detects type-incompatible changes | Call-site impact, risk scoring, runtime data integration |
| **japicmp / apidiff (Go/Java)** | API compatibility in Java / Go | Direct conceptual analog in other languages | Python-specific, runtime tracing, patch generation |

### ImpactGuard's unique differentiators

1. **Risk scoring (S × E × C)** — No competitor combines severity, exposure (call count), and confidence into a single risk score.
2. **Runtime + static fusion** — Merges static call-site analysis with actual runtime call counts from test runs to give empirically grounded risk levels.
3. **Transitive impact** — Tracks callers of callers, not just direct call sites.
4. **CST-based patch generation** — Suggests and previews source patches that preserve original formatting; no competitor does this in the API-change domain.
5. **Patch confidence scoring** — Quantifies how safe an automated fix is before applying it.
6. **Fully offline** — No network access, no database; embeds entirely in a Python project.

---

## Further Documentation

For deeper exploration of specific subsystems, refer to the [DeepWiki documentation](https://deepwiki.com/daedalus/ImpactGuard):

- [Getting Started](https://deepwiki.com/daedalus/ImpactGuard/1.1-getting-started)
- [Architecture and Data Flow](https://deepwiki.com/daedalus/ImpactGuard/1.2-architecture-and-data-flow)
- [Core Analysis Pipeline](https://deepwiki.com/daedalus/ImpactGuard/2-core-analysis-pipeline)
- [Risk Model and Enforcement](https://deepwiki.com/daedalus/ImpactGuard/3-risk-model-and-enforcement)
- [Runtime Tracing](https://deepwiki.com/daedalus/ImpactGuard/4-runtime-tracing)
- [Patch Generation and Remediation](https://deepwiki.com/daedalus/ImpactGuard/5-patch-generation-and-remediation)
- [CLI and Public API](https://deepwiki.com/daedalus/ImpactGuard/6-cli-and-public-api)
- [Git Hooks and Workflow Integration](https://deepwiki.com/daedalus/ImpactGuard/7-git-hooks-and-workflow-integration)
- [CI/CD and Release Infrastructure](https://deepwiki.com/daedalus/ImpactGuard/8-cicd-and-release-infrastructure)
- [Testing](https://deepwiki.com/daedalus/ImpactGuard/9-testing)
- [Glossary](https://deepwiki.com/daedalus/ImpactGuard/10-glossary)
