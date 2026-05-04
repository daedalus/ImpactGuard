from typing import Any

"""
ImpactGuard - Lightweight API impact analyzer for Python projects.

Track function signatures, detect breaking changes, and analyze call-site impact
using static and runtime techniques.
"""

from .compare_signatures import compare, load
from .enforce_gate import enforce
from .extract_signatures import extract, serialize_function
from .generate_report import generate_html
from .impact_analysis import analyze
from .patch_confidence import (
    classify as classify_patch,
)
from .patch_confidence import (
    compute_confidence,
    get_complexity_penalty,
    get_semantic_risk,
    get_structural_safety,
    get_target_certainty,
)
from .risk_model import (
    SEVERITY_SCORES,
    classify,
    compute_risk,
    confidence,
    exposure,
    get_severity,
)
from .pipeline import (
    run_pipeline,
    quick_check,
    run_pipeline_git,
    ImpactGuard,
)
from .patch_confidence import (  # noqa: F401
    compute_confidence,
    get_complexity_penalty,
    get_semantic_risk,
    get_structural_safety,
    get_target_certainty,
)
from .risk_model import (  # noqa: F401
    SEVERITY_SCORES,
    classify,
    compute_risk,
    confidence,
    exposure,
    get_severity,
)

__version__ = "0.2.0"
__all__ = [
    # Signature extraction
    "extract",
    "serialize_function",
    # Comparison
    "compare",
    "load",
    # Impact analysis
    "analyze",
    # Risk model
    "get_severity",
    "exposure",
    "confidence",
    "classify",
    "compute_risk",
    # Patch confidence
    "compute_confidence",
    "classify_patch",
    "get_target_certainty",
    # Reporting
    "generate_html",
    "enforce",
    # Pipeline (Recommended)
    "run_pipeline",
    "quick_check",
    "run_pipeline_git",
    "ImpactGuard",
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
