# **ImpactGuard** — Lightweight multi-language API impact analyzer

<img src="logo.png" width="300px">

[![PyPI](https://img.shields.io/pypi/v/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Python](https://img.shields.io/pypi/pyversions/impactguard.svg)](https://pypi.org/project/impactguard/)
[![Actions status](https://github.com/daedalus/impactguard/workflows/CI/badge.svg)](https://github.com/daedalus/impactguard/actions)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/daedalus/ImpactGuard)

## Overview

ImpactGuard is a lightweight API impact analyzer that supports Python, TypeScript, Java, Go, Rust, C, C++, and Ruby. It is designed to maintain API stability by tracking function signatures across commits, detecting breaking changes, and analyzing call-site impact using both static and runtime techniques.

It provides a quantitative risk framework to help developers understand the consequences of code changes before they are merged.

### Core Capabilities

- **Multi-language Extraction**: Automatically extracts function signatures from Python (`ast`), TypeScript, Java, Go, Rust, C, C++, and Ruby via tree-sitter grammars (with regex fallback)
- **Semantic API Diffing**: Classifies changes into a taxonomy of breaking (e.g., removing positional arguments) vs. non-breaking (e.g., adding optional keyword-only arguments)
- **Impact Analysis**: Correlates signature changes with static call-site extraction and optional runtime tracing to identify affected downstream code
- **Risk Assessment**: Quantifies the danger of a change using the **S × E × C × λ** (Severity × Exposure × Confidence × Lambda) model
- **Automated Remediation**: Generates format-preserving patches using LibCST to fix broken call sites

### System Components

| Component | Module | Description |
|-----------|--------|-------------|
| Signature Extraction | `extract_signatures.py` | AST-based extraction of function metadata |
| Signature Comparison | `compare_signatures.py` | Semantic diffing of API changes |
| Call-Site Analysis | `extract_calls.py`, `analyze_module.py` | Static call-site extraction and resolution |
| Impact Analysis | `impact_analysis.py` | Correlates changes with call sites |
| Risk Model | `risk_model.py` | S × E × C × λ risk scoring |
| Risk Gate | `risk_gate.py`, `enforce_gate.py` | CI enforcement engine |
| Runtime Tracing | `trace_calls.py`, `trace_calls_prod.py` | Development and production tracers |
| Patch Generation | `cst_patch.py`, `patch_generator.py` | Format-preserving automated fixes |
| Reporting | `generate_report.py` | Static HTML report generation |
| Robustness Evaluation | `tools/robustness_evaluator.py` | Composite robustness score, fragility index, diversity |
| CLI | `cli.py` | Command-line interface |

---

## Language Support

| Language | Extensions | Extraction Backend | Signature Extraction | Call-Site Extraction | Type Annotations | Optional Dependency | Status |
|----------|------------|--------------------|:--------------------:|:--------------------:|:----------------:|---------------------|--------|
| **Python** | `.py` | `ast` (stdlib) | Yes | Yes | Yes | — | Stable |
| **TypeScript** | `.ts`, `.tsx` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **JavaScript** | `.js`, `.mjs`, `.cjs` | tree-sitter (preferred) / regex fallback | Yes | Yes | No (no native annotations) | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Java** | `.java` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Kotlin** | `.kt`, `.kts` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Go** | `.go` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Rust** | `.rs` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Swift** | `.swift` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **C** | `.c`, `.h` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **C++** | `.cpp`, `.hpp`, `.cc`, `.cxx`, `.hxx` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **C#** | `.cs` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Ruby** | `.rb` | tree-sitter (preferred) / regex fallback | Yes | Yes | No (no native annotations) | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Haskell** | `.hs`, `.lhs` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes (type signatures) | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |
| **Zig** | `.zig` | tree-sitter (preferred) / regex fallback | Yes | Yes | Yes / partial | `pip install "impactguard[languages]"` | Stable (tree-sitter) · Best-effort (regex) |

> **Note:** All tree-sitter backends require `tree-sitter>=0.23` plus the corresponding grammar package
> (e.g. `tree-sitter-java>=0.23`), installed together via `pip install "impactguard[languages]"`.
> When those packages are absent, ImpactGuard automatically falls back to regex-based extraction and
> emits a `UserWarning`.
>
> **Suppression:** All languages that use C-style comments support `// impactguard: ignore` on or
> immediately before a function definition.  Python uses `# impactguard: ignore`.  Ruby uses
> `# impactguard: ignore`.  Haskell uses `-- impactguard: ignore`.
>
> **Adding new languages:** Implement the [`LanguageExtractor`](src/impactguard/languages/base.py)
> protocol and register the extractor with [`register()`](src/impactguard/languages/registry.py).
> Third-party packages can contribute extractors automatically by declaring an entry point in the
> `impactguard.languages` group — see [Plugin / Extension API](#plugin--extension-api) below.

---

## Quick Start

### Installation

**Prerequisites:**

- Python 3.11 or higher
- Dependencies: `libcst` for concrete syntax tree manipulations
- For git hooks: `pre-commit>=4.6.0`, `pyyaml>=6.0`

```bash
# Install from PyPI
pip install impactguard

# Install with tree-sitter language support (TypeScript, Java, Go, Rust, C, C++, Ruby)
pip install "impactguard[languages]"

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
# 1. Extract signatures and calls (Python — uses stdlib ast)
impactguard extract $(git ls-files '*.py') > .signatures.json
impactguard extract-calls $(git ls-files '*.py') > .calls.json

# Extract from other supported languages (requires impactguard[languages])
impactguard extract $(git ls-files '*.java' '*.go' '*.rs') > .signatures.json
impactguard extract-calls $(git ls-files '*.java' '*.go' '*.rs') > .calls.json

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
    old_files=["old_version/"],
    new_files=["new_version/"],
    runtime_path="runtime.json",  # optional
    output_dir="report.html"      # optional
)
print(f"Breaking changes: {len(result['comparison']['breaking'])}")
```

---

## Core Analysis Pipeline

ImpactGuard operates as a **pipe-and-filter architecture** where artifacts from one stage inform the next.

### 1. Signature Extraction

The first stage involves deep inspection of source files. For Python, the `ast` stdlib module is used to walk the Abstract Syntax Tree. For all other supported languages (TypeScript, Java, Go, Rust, C, C++, Ruby) tree-sitter grammars provide accurate, battle-tested AST parsing with a regex fallback when tree-sitter packages are absent. Every supported language produces the same schema: Fully Qualified Name (FQN), parameters, defaults, and decorators/annotations.

- **Key Component:** `extract_signatures.py` (Python) · `src/impactguard/languages/` (all languages)
- **Output:** `.signatures.json`
- **Role:** Establishes the baseline of the API surface

### 2. Signature Comparison

Once two snapshots of a codebase exist (e.g., `HEAD` vs `main`), the `compare` utility performs a semantic diff. Unlike a standard text-based diff, this stage understands Python's parameter rules. It categorizes changes into **Breaking** (e.g., removing a parameter, reordering positional arguments) and **Non-breaking** (e.g., adding an optional keyword argument).

- **Key Component:** `compare_signatures.py`
- **Output:** A structured list of semantic changes
- **Role:** Identifies exactly how the API contract has evolved
- **New:** The `compare` command now supports comparing source files directly (auto-extracts signatures)

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

### The S × E × C × λ Risk Framework

The core logic resides in `risk_model.py`. It quantifies risk by evaluating three distinct dimensions, scaled by a tuneable sensitivity multiplier λ:

| Component | Code Entity | Description |
|-----------|-------------|-------------|
| **Severity (S)** | `get_severity()` | Score (0.1 to 1.0) based on change type (e.g., `REMOVED` = 1.0, `ADDED` = 0.1) |
| **Exposure (E)** | `exposure()` | Logarithmic scale mapping call counts to a 0.0-1.0 range |
| **Confidence (C)** | `confidence()` | Measures data reliability based on sample size against a threshold |
| **Lambda (λ)** | `--lambda` / `lambda_` | Sensitivity multiplier (default 1.0). Values >1 increase sensitivity; values <1 decrease it |
| **Classification** | `classify()` | Uses a decision tree to assign the final risk label |

**Exposure Calculation:** `min(1.0, log(1 + count) / log(1 + max_count))`

**Sensitivity Tuning:**
- `--lambda=2` — doubles effective severity, making ImpactGuard more sensitive (more changes flagged HIGH/MEDIUM)
- `--lambda=0.5` — halves effective severity, making ImpactGuard less sensitive (fewer changes flagged HIGH/MEDIUM)

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

### Usage

```
impactguard [-h] [--version]
            {extract,compare,analyze,risk,report,enforce,suggest,patch,extract-calls,trace,check,check-diff,check-commit,check-commits,install-hooks,generate-changelog,baseline,semver,report-markdown,feedback,history} ...

ImpactGuard - API impact analyzer for Python

positional arguments:
  {extract,compare,analyze,risk,report,enforce,suggest,patch,extract-calls,trace,check,check-diff,check-commit,check-commits,install-hooks,generate-changelog,baseline,semver,report-markdown,feedback,history}
                        Available commands
    extract             Extract function signatures from source files
    compare             Compare signature snapshots or source files directly
    analyze             Analyze impact on call sites
    risk                Run risk analysis
    report              Generate HTML report
    enforce             Enforce gate - block on HIGH risk
    suggest             Generate fix suggestions from risk report
    patch               Generate CST-based patches
    extract-calls       Extract call sites from source files
    trace               Runtime tracing
    check               Run full ImpactGuard pipeline check
    check-diff          Run full pipeline on a unified diff / patch file
    check-commit        Run full pipeline on a single git commit vs its parent
    check-commits       Compare two git commits
    install-hooks       Install git hooks for ImpactGuard
    generate-changelog  Generate changelog from signature diffs
    baseline            Manage ImpactGuard signature baselines
    semver              Suggest semver bump from two signature snapshots
    report-markdown     Generate markdown PR comment from risk report JSON
    feedback            Manage patch-outcome feedback for confidence calibration
    history             Manage tagged release-history baselines

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

### Pipeline Mode (Recommended)

```bash
# Compare two versions of your code
impactguard old_version/ new_version/

# Compare two git commits directly
impactguard check-commits HEAD~1 HEAD

# Compare specific files between commits
impactguard check-commits HEAD~1 HEAD --files src/module.py src/utils.py

# Generate patch files for suggested fixes
impactguard check --suggest-patch old.py new.py

# Show how old file would look if patched (requires --suggest-patch)
impactguard check --suggest-patch --show-patch old.py new.py
```

**Patch Generation Flags:**
- `--suggest-patch`: Generate and save patch files to `patches/` directory
- `--show-patch`: Display patched content inline (depends on `--suggest-patch`)

### Individual Commands (Advanced)

```bash
impactguard extract file1.py file2.py
impactguard compare old_sigs.json new_sigs.json
# Or compare source files directly (auto-extracts signatures):
impactguard compare old.py new.py
impactguard analyze signatures.json calls.json runtime.json
impactguard risk diff.txt runtime.json output.json
impactguard report risk.json output.html
impactguard trace install mypackage
impactguard trace dump runtime.json
impactguard install-hooks . --both  # Install git hooks
```

### Git Hooks Installation

ImpactGuard uses the `pre-commit` framework to manage git hooks with proper YAML configuration.

```bash
# Install both pre-commit and post-commit hooks
impactguard install-hooks .

# Install only pre-commit hook
impactguard install-hooks . --pre

# Install only post-commit hook
impactguard install-hooks . --post

# Install hooks + GitHub Actions workflow
impactguard install-hooks . --install-github-workflow
```

The `install-hooks` command:
1. Creates/updates `.pre-commit-config.yaml` with ImpactGuard hooks (using PyYAML for proper formatting)
2. Runs `pre-commit install` and `pre-commit install --hook-type post-commit`
3. Optionally generates `.github/workflows/impactguard.yml` for CI/CD

**Hook behavior:**
- **Pre-commit**: Runs full ImpactGuard pipeline (`check-diff --pipe`) on staged changes
- **Post-commit**: Runs `check-commit HEAD` + updates signature tracking

---

## Python Library API

The `impactguard` package exports its core functionality for programmatic integration.

### Pipeline (Recommended)

```python
from impactguard import run_pipeline, quick_check, run_pipeline_git, ImpactGuard

# Full pipeline - extract, compare, analyze, risk, report
result = run_pipeline(
    old_files=["src/"],
    new_files=["src/"],
    runtime_path="runtime.json",
    output_dir="report.html",
    suggest_patch=True,  # Generate patch files
    show_patch=True,     # Display patched content inline
)

# Quick comparison only (extract + compare)
changes = quick_check("old/", "new/")
print(f"Breaking: {len(changes['comparison']['breaking'])}")

# Compare git commits
result = run_pipeline_git(
    old_ref="HEAD~1",
    new_ref="HEAD",
    files=["src/module.py"],
    suggest_patch=True,
    show_patch=True,
)

# Use ImpactGuard class for more control
guard = ImpactGuard()
report = guard.check("old/", "new/", output="report.html")
```

**Patch Generation Parameters:**
- `suggest_patch=True`: Generate and save patch files to `patches/` directory
- `show_patch=True`: Display how old file would look if patched (requires `suggest_patch=True`)

### Individual Components (Advanced)

```python
from impactguard import extract, compare, analyze_impact

# Extract signatures from Python files
signatures = extract(["src/module.py", "src/other.py"])

# Extract from other supported languages (tree-sitter backend)
signatures = extract(["src/main.go", "src/utils.go"])
signatures = extract(["src/lib.rs", "src/main.rs"])

# Compare two signature snapshots or source files directly
result = compare("old_sigs.json", "new_sigs.json")
# Or compare source files directly (auto-extracts signatures):
result = compare("old.py", "new.py")
print(f"Breaking changes: {len(result['breaking'])}")

# Analyze impact on call sites
issues = analyze_impact("signatures.json", "calls.json", "runtime.json")
```

---

## Git Hooks and Workflow Integration

ImpactGuard integrates deeply into the standard Git development workflow using the `pre-commit` framework.

### Pre-Commit Hook (Full Pipeline Check)

Runs the complete ImpactGuard pipeline on staged changes before allowing a commit:

```bash
impactguard check-diff --pipe --runtime .runtime_calls.json
```

This catches breaking changes early, before they enter the commit history.

### Post-Commit Hook (Signature Tracking)

After each commit, the post-commit hook:
1. Runs `check-commit HEAD` to analyze the committed changes
2. Updates `.signatures.txt` with current function signatures

### GitHub Actions Workflow

Generate a ready-to-use CI workflow with:

```bash
impactguard install-hooks . --install-github-workflow
```

This creates `.github/workflows/impactguard.yml` that:
- Triggers on push/PR to `main`/`master`
- Runs `check-commits` for pull requests
- Runs `check-commit` for direct pushes
- Uses `impactguard[all]` for full language support

### Console Scripts

The hooks use these entry points (automatically configured):
- `impactguard-check-staged` → runs pipeline on staged diff
- `impactguard-post-commit-hook` → runs post-commit analysis

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

1. **Signature Extraction** — Parses Python AST (stdlib) or tree-sitter grammars (TypeScript, Java, Go, Rust, C, C++, Ruby) to extract function signatures with full structural information
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

- **Signature**: A structured representation of a callable's interface, including positional arguments, keyword-only arguments, variadic arguments, and return type. Supported for Python, TypeScript, Java, Go, Rust, C, C++, and Ruby.
- **FQName (Fully Qualified Name)**: A unique identifier in `file_path:function_name` format (e.g., `src/auth.py:login`)
- **Breaking Change**: A modification that prevents existing callers from executing correctly (e.g., `REMOVED`, `REQUIRED_POSITIONAL_ADDED`, `POSITIONAL_REORDER`)

### Risk Framework (S × E × C × λ)

- **Severity (S)**: The technical impact of the change type (0.1 to 1.0)
- **Exposure (E)**: How often the function is called, calculated logarithmically
- **Confidence (C)**: The reliability of runtime data based on sample size
- **Lambda (λ)**: Sensitivity multiplier (default 1.0); tune via `--lambda`

### Patching

- **CST (Concrete Syntax Tree)**: Unlike AST, preserves formatting, comments, and whitespace
- **Patch Confidence**: A score from 0.0 to 1.0 representing the likelihood that an automated fix is correct

---

## Direct Competitors (Python API analysis space)

The table below compares ImpactGuard against the tools most commonly used for Python API change management, static analysis, and release automation. As of 2026-05, to our knowledge:

| Feature | **ImpactGuard** | **griffe** | **python-semantic-release** | **commitizen** | **pyright / mypy** |
|---|---|---|---|---|---|
| AST-based signature extraction | ✅ Full — Python (`ast`), TypeScript/Java/Go/Rust/C/C++/Ruby (tree-sitter) | ✅ Full (Python) | ❌ | ❌ | ✅ (internal only) |
| Breaking-change detection | ✅ Semantic diff (added / removed / modified) | ✅ | ❌ Code-unaware | ❌ Code-unaware | ⚠️ Type errors only |
| Call-site impact analysis | ✅ Static call-site traversal | ❌ | ❌ | ❌ | ❌ |
| Runtime call tracing | ✅ (test + production sampler) | ❌ | ❌ | ❌ | ❌ |
| Risk scoring (S × E × C × λ model) | ✅ | ❌ | ❌ | ❌ | ❌ |
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
| **japicmp / apidiff (Go/Java)** | API compatibility in Java / Go | Direct conceptual analog in other languages | Python + TypeScript + Java + Go + Rust + C/C++ + Ruby support, runtime tracing, patch generation |

### ImpactGuard's unique differentiators

1. **Risk scoring (S × E × C × λ)** — No competitor combines severity, exposure (call count), and confidence into a single risk score.
2. **Runtime + static fusion** — Merges static call-site analysis with actual runtime call counts from test runs to give empirically grounded risk levels.
3. **Transitive impact** — Tracks callers of callers, not just direct call sites.
4. **CST-based patch generation** — Suggests and previews source patches that preserve original formatting; no competitor does this in the API-change domain.
5. **Patch confidence scoring** — Quantifies how safe an automated fix is before applying it.
6. **Fully offline** — No network access, no database; embeds entirely in a Python project.

---

## Robustness Evaluator (`tools/robustness_evaluator.py`)

The **Robustness Evaluator** computes a composite project-level **Robustness Score (R)** from test-suite metrics, placing extra emphasis on adversarial test performance. It also reports an **Adversarial Fragility Index (F)** that isolates how much adversarial inputs specifically degrade the system.

### Metrics

| Metric | Formula | Description |
|--------|---------|-------------|
| **R** | `C × (α × P_a + (1−α) × P_n) × S` | Composite Robustness Score — overall health in [0, 1] |
| **R_d** | `C × D × (α × P_a + (1−α) × P_n) × S` | R with category diversity penalty |
| **F** | `max(0, (P_n - P_a) / P_n)` | Fragility Index — bounded to [0, 1] |
| **D** | `mean(pass_rate_i)` | Weighted diversity (mean pass rate across categories) |
| **S** | `sample_penalty` | Sample size penalty (1.0 when n ≥ 10, decreases for small samples) |

**Input symbols:**

| Symbol | Meaning |
|--------|---------|
| `C` | Coverage ratio (0 – 1) |
| `α` | Adversarial weight; recommended 0.5 (general), 0.65 (security), 0.75 (red-team) |
| `P_a` | Adversarial pass rate (`passing_adv / n_adversarial`) |
| `P_n` | Normal pass rate (`passing_norm / n_normal`) |

**Robustness labels:** EXCELLENT (≥ 0.80) · GOOD (≥ 0.65) · FAIR (≥ 0.45) · POOR (< 0.45)
- **Floor:** If `P_a < 0.3`, robustness label is capped to **POOR** regardless of score

**Fragility labels:** ROBUST (F ≤ 0.10) · MODERATE (≤ 0.25) · BRITTLE (≤ 0.50) · VERY_BRITTLE (> 0.50)
- **Bounded:** F is clamped to [0, 1]; when `P_a ≥ P_n`, F = 0.0 (not brittle)

**Sample size penalty:** Applied when adversarial or normal sample < 10 tests (linear ramp from 0.3 to 1.0)

The tool enforces a **minimum 25% adversarial coverage** requirement (exits with code 0, outputs warning to stderr).

### Adversarial Budget Allocation

| Category | Target % of adversarial budget | Example |
|----------|--------------------------------|---------|
| Boundary/edge cases | 30% | Inputs at decision boundaries |
| Semantic perturbation | 25% | Same meaning, different form |
| Evasion/obfuscation | 25% | Encoding tricks, reformulation |
| Compositional attacks | 20% | Multi-step, chained inputs |

### Usage

**Python API:**

```python
from tools.robustness_evaluator import evaluate_robustness, CategoryStats

result = evaluate_robustness(
    n_total=1054,
    n_adversarial=425,
    passing_adv=424,
    passing_norm=629,
    coverage=0.57,
    alpha=0.65,            # security context
    categories=[
        CategoryStats("boundary",       28, 28, difficulty=1.0),  # hard
        CategoryStats("semantic",       22, 22, difficulty=0.5),  # medium
        CategoryStats("evasion",        24, 24, difficulty=1.0),  # hard
        CategoryStats("compositional",  19, 19, difficulty=0.8),  # hard
    ],
)

print(f"R  = {result.robustness_score:.4f}  [{result.robustness_label}]")
print(f"F  = {result.fragility_index:.4f}  [{result.fragility_label}]")
print(f"R_d = {result.robustness_score_with_diversity:.4f}  (with diversity)")
print(f"S  = {result.sample_penalty:.2f}  (sample penalty)")
```

**CLI (human-readable report) — empirical run from current test suite:**

```bash
python tools/robustness_evaluator.py \
  --n-total 1054 \
  --n-adversarial 425 \
  --passing-adv 424 \
  --passing-norm 629 \
  --coverage 0.57 \
  --alpha 0.65 \
  --categories '[{"name":"boundary","total":28,"passing":28,"difficulty":1.0},
                 {"name":"semantic","total":22,"passing":22,"difficulty":0.5},
                 {"name":"evasion","total":24,"passing":24,"difficulty":1.0},
                 {"name":"compositional","total":19,"passing":19,"difficulty":0.8}]'
```

**CLI (JSON output for CI pipelines):**

```bash
python tools/robustness_evaluator.py --n-total 1054 --n-adversarial 425 \
  --passing-adv 424 --passing-norm 629 --coverage 0.57 --json
```

**Empirical output (measured from actual test runs):**

```
===========================================================
  ImpactGuard — Robustness Evaluation Report
===========================================================

── Test Composition ──────────────────────────────────────
  Total tests        : 1054
  Adversarial tests  : 425
  Normal tests       : 629
  Adversarial ratio  : 40.3%  ✓

── Pass Rates ────────────────────────────────────────────
  P_adversarial (P_a): 0.998
  P_normal      (P_n): 1.000
  Coverage      (C)  : 0.570
  Alpha         (α)  : 0.65
  Diversity     (D)  : 1.000

── Primary Metrics ───────────────────────────────────────
  Robustness Score (R)          : 0.5691  [FAIR]
  Sample Penalty (S)           : 1.00
  Robustness + Diversity (R_d)  : 0.5691
  Fragility Index (F)           : 0.0000  [ROBUST]

── Category Breakdown ────────────────────────────────────
  boundary              28/28  (100%)  ●●●●●●●●●●●●●●●●●●●●●●●●●●
  semantic              22/22  (100%)  ●●●●●●●●●●●●●●●●●●●●●●
  evasion               24/24  (100%)  ●●●●●●●●●●●●●●●●●●●●●●●●
  compositional         19/19  (100%)  ●●●●●●●●●●●●●●●●●●●

===========================================================
```

**Low sample size output example:**

```
── Primary Metrics ───────────────────────────────────────
  Robustness Score (R)          : 0.0774  [POOR]
  Sample Penalty (S)           : 0.19 (small sample)

⚠ WARNING: Low coverage (<30%) - consider adding tests

============================================================
  ImpactGuard — Robustness Evaluation Report
============================================================

── Test Composition ──────────────────────────────────────
  Total tests        : 1054
  Adversarial tests  : 425
  Normal tests       : 629
  Adversarial ratio  : 40.3%  ✓

── Pass Rates ────────────────────────────────────────────
  P_adversarial (P_a): 0.998
  P_normal      (P_n): 1.000
  Coverage      (C)  : 0.570
  Alpha         (α)  : 0.65
  Diversity     (D)  : 1.000

── Primary Metrics ───────────────────────────────────────
  Robustness Score (R)          : 0.5691  [FAIR]
  Robustness + Diversity (R_d)  : 0.5691
  Fragility Index (F)           : 0.0024  [ROBUST]

── Category Breakdown ────────────────────────────────────
  boundary              28/28  (100%)  ●●●●●●●●●●●●●●●●●●●●●●●●●●●●
  semantic              22/22  (100%)  ●●●●●●●●●●●●●●●●●●●●●●
  evasion               24/24  (100%)  ●●●●●●●●●●●●●●●●●●●●●●●●
  compositional         19/19  (100%)  ●●●●●●●●●●●●●●●●●●●

============================================================
```

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
