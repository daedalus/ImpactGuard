# Contributing to ImpactGuard

Thank you for contributing to ImpactGuard!

## Development Setup

```bash
git clone https://github.com/daedalus/ImpactGuard.git
cd ImpactGuard
pip install -e ".[test]"
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Quality

All PRs must pass:

- **Ruff** (formatting + linting): `ruff check src/`
- **MyPy** (strict mode): `mypy --strict src/`
- **Tests**: `pytest tests/`
- **Coverage**: ≥80%

## Git Hooks

Install the ImpactGuard hooks in your local repo:

```bash
impactguard install-hooks . --both
```

- **pre-commit**: Extracts signatures from staged `.py` files
- **post-commit**: Updates signature tracking after each commit

The `SKIP_SIGNATURE_HOOK=1` environment variable prevents infinite recursion.

## Release Process

1. Bump version: `bumpversion patch` (or `minor`/`major`)
2. Update `CHANGELOG.md`
3. Push to `master` and create a GitHub Release
4. CI automatically publishes to PyPI via Trusted Publishers (OIDC)

## Adding Change-Type Detectors

Change detection lives in `compare_signatures.py`. To add a new change type:

1. Add detection logic in `compare()` function
2. Add the new change type key to `SEVERITY_SCORES` in `risk_model.py`
3. Add tests in `tests/`

## Architecture

See `SPEC.md` for the full technical specification and public API documentation.
See `AGENTS.md` for guidelines when using AI agents to contribute.

## AI-Assisted Contributions

Some commits in this repository have been scaffolded or authored with the
assistance of AI coding agents (see `AGENTS.md`).  The project policy is:

- Every AI-generated commit must be reviewed and approved by a human
  maintainer before merging.
- The human reviewer is responsible for correctness, security, and design
  fit — AI output is treated as a first draft, not a finished patch.
- AI-generated code is held to the same quality bar as human-written code
  (type annotations, tests, linting, coverage).

## Project Layout

| Path | Description |
|------|-------------|
| `src/impactguard/` | Core package |
| `tests/` | All tests |
| `SPEC.md` | Technical specification and public API |
| `AGENTS.md` | AI agent contribution guidelines |
| `CHANGELOG.md` | Version history |
