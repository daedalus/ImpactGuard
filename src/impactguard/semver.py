"""Semantic-version bump suggestion based on API comparison results.

Given the output of :func:`compare_signatures.compare`, this module maps
breaking vs. non-breaking changes to the appropriate semver bump level.

Rules:
    * Any breaking change → **major** bump (incompatible API change).
    * Only non-breaking additions/changes → **minor** bump (backward-compatible).
    * No observable API changes → **patch** bump (internal / bug-fix only).
"""

from typing import Any


# Change prefixes that indicate a breaking API change
_BREAKING_PREFIXES = (
    "REMOVED:",
    "POSITIONAL REMOVED:",
    "POSITIONAL REORDER",
    "REQUIRED POSITIONAL ADDED:",
    "REQUIRED KWONLY ADDED:",
    "KWONLY REMOVED:",
    "*args REMOVED:",
    "**kwargs REMOVED:",
    "TYPE CHANGED:",
    "RETURN TYPE CHANGED:",
    "DECORATOR REMOVED:",
    "DECORATOR ADDED:",
    # NOTE: "DEPRECATED REMOVED:" is intentionally excluded — it is non-breaking.
    # NOTE: "TYPE WIDENED:" and "RETURN TYPE WIDENED:" are non-breaking.
)


def suggest_semver(comparison: dict[str, list[str]]) -> str:
    """Suggest a semver bump level from a signature comparison result.

    Args:
        comparison: Dictionary with ``"breaking"`` and ``"nonbreaking"`` lists
            as returned by :func:`compare_signatures.compare`.

    Returns:
        One of ``"major"``, ``"minor"``, or ``"patch"``.
    """
    breaking = comparison.get("breaking", [])
    nonbreaking = comparison.get("nonbreaking", [])

    if breaking:
        return "major"
    if nonbreaking:
        return "minor"
    return "patch"


def format_semver_recommendation(
    comparison: dict[str, list[str]],
    current_version: str | None = None,
) -> dict[str, Any]:
    """Build a structured semver recommendation.

    Args:
        comparison: Signature comparison result.
        current_version: Optional current version string (e.g. ``"1.2.3"``).

    Returns:
        Dictionary with keys:
            * ``bump``: ``"major"``, ``"minor"``, or ``"patch"``
            * ``reason``: Human-readable explanation
            * ``breaking_count``: Number of breaking changes
            * ``nonbreaking_count``: Number of non-breaking changes
            * ``next_version``: Suggested next version (if *current_version* is given)
    """
    bump = suggest_semver(comparison)
    breaking = comparison.get("breaking", [])
    nonbreaking = comparison.get("nonbreaking", [])

    reasons: dict[str, str] = {
        "major": f"{len(breaking)} breaking change(s) detected — callers must update",
        "minor": f"{len(nonbreaking)} backward-compatible addition(s) — callers unaffected",
        "patch": "No public API changes detected",
    }

    result: dict[str, Any] = {
        "bump": bump,
        "reason": reasons[bump],
        "breaking_count": len(breaking),
        "nonbreaking_count": len(nonbreaking),
    }

    if current_version:
        result["next_version"] = _increment(current_version, bump)

    return result


_MIN_SEMVER_PARTS = 3  # major.minor.patch


def _increment(version: str, bump: str) -> str:
    """Increment a semver string by *bump* level.

    Non-semver strings are returned unchanged with ``"-next"`` appended.
    """
    parts = version.lstrip("v").split(".")
    if len(parts) < _MIN_SEMVER_PARTS:
        return version + "-next"
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return version + "-next"

    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
