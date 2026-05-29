# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- SARIF support row to competitor comparison table in README

## [v0.1.11] - 2026-05-29

### Added

- SARIF v2.1.0 output support (`report-sarif` subcommand, `--report-sarif` flag)

### Test

- Adversarial SARIF tests

## [v0.1.10] - 2026-05-28

### Added

- Adversarial tests for pipeline diff, check_staged, and `_parse_unified_diff`

## [v0.1.9] - 2026-05-21

### Added

- CST fix generation wired into pipeline and CLI

### Changed

- Refactored to reduce lizard cyclomatic complexity hotspots

## [v0.1.8] - 2026-05-20

### Added

- Semantic behavior analysis beyond signature-level compatibility
- Runtime intelligence input normalization
- CI gating hardening and strict analysis enforcement

### Changed

- Refactored to reduce lizard complexity hotspots, closure warnings, and Codacy lint warnings
- Deduplicated C and C++ extractor class logic
- Shared change parsing and risk severity sentinel logic

### Fixed

- Removed redundant `SyntaxWarning` and fixed version test
- Narrowed overly-broad `except Exception` clauses
- Used `tempfile.gettempdir()` instead of hardcoded `/tmp` path (CWE-377)
- Restored missing `extract_calls_with_tree_sitter` in shared.py

## [v0.1.6] - 2026-05-15

### Fixed

- Hardened CLI against malformed inputs and stdin hang
- Hardened path validation against Windows-style payloads
- Widen tree-sitter-kotlin and tree-sitter-zig upper bounds to `<2`

### Test

- Added reproducible smoke reliability checks and pipeline analysis status
- Added tests for null-byte diff regression and malicious diff path payloads

## [v0.1.5] - 2026-05-13

### Fixed

- Fixed 7 security findings from black-box red team audit

### Docs

- Added website badge (impactguard.dev) to README

## [v0.1.4] - 2026-05-13

### Added

- Logging facilities (`get_logger`, `configure_logging`, `--log-file` option)
- Wire logging config options through CLI
- Vulture to CI and pre-commit with `--min-confidence 90`

### Fixed

- Added missing `check_staged` and `post_commit_hook` entry points to `__init__.py`
- Restored missing `extract_calls_with_tree_sitter` in shared.py
- Invalid log level handling

### Changed

- Deduplicated shared language extractor logic
- Aligned dedupe helper behavior with existing semantics

## [v0.1.3] - 2026-05-09

### Added

- KPI dashboard module, CLI subcommand, and tests
- Complete S×E×C metrics — mean_severity, mean_confidence, transitive_impact

### Changed

- Reorganized languages into `lib/` subdirectory
- Decoupled registry from language modules
- Extracted shared language utilities
- Deduplicated language extractors

### Fixed

- Spelling consistency (American English)
- Docstring KPI count (10→12)
- Pre-existing test failures

## [v0.1.2] - 2026-05-07

### Added

- `--show-patch` flag to display patched content inline

### Fixed

- Addressed red team findings in robustness_evaluator
- Fixed conceptual issues in robustness scoring

### Docs

- Updated README with `--show-patch` flag and compare command enhancements
- Updated logo.png

## [v0.1.1] - 2026-05-06

### Added

- Multi-language extractors: Java, Go, Rust, C, C++, Ruby, JavaScript, Kotlin, Swift, Zig, C#, Haskell
- Tree-sitter integration with regex fallback
- `--lambda` parameter to risk model (S×E×C×λ)
- Adversarial generator with 10 camouflage strategies
- Robustness evaluator and estimator wired to test suite
- GitHub workflow generation and pre-commit hook framework
- `--log-file` option with logging support
- `validate-config` command and `--apply` flag
- Multi-language watch mode

### Changed

- Switched all change types from space to underscore format
- Updated CLI documentation and language support table in README
- Wired class hierarchy into pipeline (#4) and multi-language registry into diff/commit pipeline

### Fixed

- Critical bugs: runtime key lookup, REMOVED/REQUIRED bypass, language extractor issues
- Made `get_severity()` consistent with `_is_unconditional_high()`
- Corrected overcorrection in unconditional HIGH logic
- Fixed spelling and comment clarity in adversarial_generator
- Fixed duplicate fqname key in test dict
- Resolved all pre-commit hook errors

### Test

- Added 285+ comprehensive coverage and adversarial tests

## [v0.1.0] - 2026-05-05

### Added

- Initial release
- Python AST-based signature extraction
- Semantic signature comparison
- Call-site extraction and impact analysis
- S×E×C risk model
- Runtime tracing (dev + production sampler)
- HTML report generation
- Patch confidence scoring
- CST-based patch generation
- CLI with subcommands
- Git hook integration (pre + post commit)
- GitHub Actions CI/CD workflows
- Pre-commit framework support
- SPEC.md with API documentation

[v0.1.11]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.11
[v0.1.10]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.10
[v0.1.9]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.9
[v0.1.8]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.8
[v0.1.6]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.6
[v0.1.5]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.5
[v0.1.4]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.4
[v0.1.3]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.3
[v0.1.2]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.2
[v0.1.1]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.1
[v0.1.0]: https://github.com/daedalus/ImpactGuard/releases/tag/v0.1.0
