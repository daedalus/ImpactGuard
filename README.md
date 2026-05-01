# ImpactGuard

A lightweight API impact analyzer for Python projects. Tracks function signatures, detects breaking changes, and analyzes call-site impact using static and runtime techniques.

## Features

- **AST-based signature extraction** — handles `async def`, decorators, type hints, `*args`, `**kwargs`
- **Semantic API diff** — classifies changes as breaking vs non-breaking
- **Call-site extraction** — finds all function/method calls in your codebase
- **Import-aware resolution** — resolves `from x import y`, aliases, and basic class context
- **Type-informed analysis** — uses type annotations and constructor inference
- **Runtime tracing** — optionally records actual calls during test runs
- **Post-commit hook** — automatically keeps `.signatures.txt` in sync

## Files

| File | Purpose |
|------|---------|
| `extract_signatures.py` | Extract structured function signatures as JSON |
| `compare_signatures.py` | Semantic diff between two signature snapshots |
| `extract_calls.py` | Extract call sites from Python source |
| `analyze_module.py` | Type-aware module analyzer with scope tracking |
| `impact_analysis.py` | Static call-site impact analysis |
| `trace_calls.py` | Runtime call tracer for empirical impact analysis |
| `runtime_impact.py` | Compare runtime calls against new API signatures |
| `AGENTS.md` | Documentation for agentic coding workflows |

## Quick Start

```bash
# Extract signatures from all tracked Python files
python3 extract_signatures.py $(git ls-files '*.py') > .signatures.txt

# Compare two signature snapshots
python3 compare_signatures.py old_sigs.json new_sigs.json

# Extract call sites
python3 extract_calls.py $(git ls-files '*.py') > .calls.json

# Static impact analysis
python3 impact_analysis.py .signatures.json .calls.json

# Runtime tracing (in your test suite)
# Add to conftest.py:
#   import trace_calls
#   import mypackage
#   trace_calls.install_tracer(mypackage)
```

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
