from typing import Any

"""
ImpactGuard - Lightweight API impact analyzer for Python projects.

Track function signatures, detect breaking changes, and analyze call-site impact
using static and runtime techniques.
"""
from .analyze_module import analyze as analyze_module
from .analyze_module import analyze_calls
from .baseline import (
    baseline_exists,
    compare_with_baseline,
    compare_with_tagged_baseline,
    delete_tagged_baseline,
    list_baselines,
    load_baseline,
    load_tagged_baseline,
    save_baseline,
    save_tagged_baseline,
)
from .class_hierarchy import (
    extract_class_hierarchy,
    find_implementations,
    get_cascade_changes,
)
from .compare_signatures import compare, load
from .config import get as get_config_value
from .config import get_config, load_config, reload_config, validate_config
from .cst_patch import patch_call, patch_function
from .enforce_gate import enforce, enforce_report
from .extract_signatures import extract, extract_reexports, serialize_function
from .feedback import (
    apply_weights_to_config,
    compute_calibrated_weights,
    load_outcomes,
    record_outcome,
)
from .feedback import (
    get_stats as get_feedback_stats,
)
from .generate_report import (
    generate_html,
    generate_html_from_file,
    generate_markdown,
    generate_markdown_from_file,
)
from .impact_analysis import analyze, build_call_graph, find_transitive_callers
from .languages import (
    LanguageExtractor,
    detect_language,
    get_extractor,
    get_extractor_by_language,
    list_languages,
)
from .languages import (
    list_extensions as list_language_extensions,
)
from .languages import (
    register as register_language,
)
from .patch_confidence import (
    classify as classify_patch,
)
from .patch_confidence import (
    classify_with_factors,
    compute_confidence,
    get_complexity_penalty,
    get_semantic_risk,
    get_structural_safety,
    get_target_certainty,
)
from .pipeline import (
    ImpactGuard,
    quick_check,
    run_pipeline,
    run_pipeline_commit,
    run_pipeline_diff,
    run_pipeline_diff_content,
    run_pipeline_git,
)
from .risk_model import (
    SEVERITY_SCORES,
    classify,
    compute_risk,
    confidence,
    exposure,
    get_severity,
)
from .schema import (
    validate,
    validate_risk_report,
    validate_runtime,
)
from .schema import (
    validate_calls as validate_calls_data,
)
from .schema import (
    validate_signatures as validate_signatures_data,
)
from .adversarial_generator import (
    AdversarialPair,
    generate as generate_adversarial,
    generate_all as generate_all_adversarial,
    list_strategies as list_adversarial_strategies,
)
from .semver import format_semver_recommendation, suggest_semver
from .suggest_fixes import enrich_with_fixes, get_line, suggest
from .trace_calls import dump as dump_trace
from .trace_calls import install_tracer, trace
from .trace_calls_prod import (
    flush,
    should_sample,
)
from .trace_calls_prod import (
    install_tracer as install_tracer_prod,
)

__version__ = "0.1.0"
__all__ = [
    # Signature extraction
    "extract",
    "serialize_function",
    "extract_reexports",
    # Comparison
    "compare",
    "load",
    # Impact analysis
    "analyze",
    "analyze_module",
    "analyze_calls",
    "build_call_graph",
    "find_transitive_callers",
    # Risk model
    "SEVERITY_SCORES",
    "get_severity",
    "exposure",
    "confidence",
    "classify",
    "compute_risk",
    # Patch confidence
    "compute_confidence",
    "classify_patch",
    "classify_with_factors",
    "get_target_certainty",
    "get_structural_safety",
    "get_semantic_risk",
    "get_complexity_penalty",
    # Reporting
    "generate_html",
    "generate_html_from_file",
    "generate_markdown",
    "generate_markdown_from_file",
    "enforce",
    "enforce_report",
    # CST patches
    "patch_function",
    "patch_call",
    # Suggest fixes
    "suggest",
    "enrich_with_fixes",
    "get_line",
    # Runtime tracing
    "trace",
    "install_tracer",
    "dump_trace",
    "flush",
    "should_sample",
    "install_tracer_prod",
    # Pipeline (Recommended)
    "run_pipeline",
    "quick_check",
    "run_pipeline_git",
    "run_pipeline_diff",
    "run_pipeline_diff_content",
    "run_pipeline_commit",
    "ImpactGuard",
    # Config
    "get_config",
    "load_config",
    "reload_config",
    "get_config_value",
    # Semver
    "suggest_semver",
    "format_semver_recommendation",
    # Baseline (single)
    "save_baseline",
    "load_baseline",
    "compare_with_baseline",
    "baseline_exists",
    # Baseline (multi / history)
    "save_tagged_baseline",
    "load_tagged_baseline",
    "list_baselines",
    "compare_with_tagged_baseline",
    "delete_tagged_baseline",
    # Schema validation
    "validate_signatures_data",
    "validate_calls_data",
    "validate_runtime",
    "validate_risk_report",
    "validate",
    # Class hierarchy / Protocol cascade
    "extract_class_hierarchy",
    "find_implementations",
    "get_cascade_changes",
    # Feedback loop
    "record_outcome",
    "load_outcomes",
    "get_feedback_stats",
    "compute_calibrated_weights",
    "apply_weights_to_config",
    # Adversarial generator
    "AdversarialPair",
    "generate_adversarial",
    "generate_all_adversarial",
    "list_adversarial_strategies",
    # Language registry
    "LanguageExtractor",
    "register_language",
    "get_extractor",
    "get_extractor_by_language",
    "detect_language",
    "list_languages",
    "list_language_extensions",
]


def extract_signatures(files: list[str]) -> list[dict[str, Any]]:
    """Extract function signatures from Python files.

    Args:
        files: List of Python file paths.

    Returns:
        List of signature dictionaries.
    """
    return extract(files)


def compare_signatures(old_path: str, new_path: str) -> dict[str, list[str]]:
    """Compare two signature snapshots.

    Args:
        old_path: Path to old signatures JSON.
        new_path: Path to new signatures JSON.

    Returns:
        Dictionary with 'breaking' and 'nonbreaking' lists.
    """
    return compare(old_path, new_path)


def analyze_impact(
    sigs_path: str, calls_path: str, runtime_path: str | None = None
) -> list[dict[str, Any]]:
    """Analyze impact of signature changes on call sites.

    Args:
        sigs_path: Path to signatures JSON file.
        calls_path: Path to calls JSON file.
        runtime_path: Optional path to runtime data JSON.

    Returns:
        List of impact issues.
    """
    return analyze(sigs_path, calls_path, runtime_path)
