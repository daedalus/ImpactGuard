# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- SPEC.md with complete API documentation
- CHANGELOG.md
- pyproject.toml with hatchling build system
- `.pre-commit-config.yaml` for automated linting
- `.github/workflows/ci.yml` for CI/CD
- `.github/workflows/pypi-publish.yml` for PyPI publishing
- `.bumpversion.cfg` for version management
- `src/` layout for proper package structure
- `py.typed` marker for PEP 561 compliance
- `tests/conftest.py` with shared fixtures
- Complete type hints and docstrings

### Changed

- Migrated from setuptools to hatchling build system
- Reorganized project to src/ layout
- Updated README.md with shields and proper documentation
- Moved internal tests from package to tests/ directory

### Fixed

- Added missing project files required by scaffold standard
- Improved test structure with proper fixtures

## [0.2.0] - 2026-01-XX

### Added

- Initial release with core functionality
- AST-based signature extraction
- Semantic signature comparison
- Call-site extraction and impact analysis
- Risk model with S × E × C scoring
- Runtime tracing capabilities
- HTML report generation
- Patch confidence scoring
- CST-based patch generation
- CLI interface with subcommands
- Post-commit hook for signature tracking

[0.2.0]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.2.0
