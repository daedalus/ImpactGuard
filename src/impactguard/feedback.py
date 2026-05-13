"""Patch-outcome feedback loop for ImpactGuard.

Records whether suggested patches were accepted or rejected, computes
acceptance-rate-based weights, and can apply those weights back to the
``impactguard.toml`` config file so future patch-confidence scoring is
calibrated against real-world outcomes.

Storage format
--------------
Outcomes are appended to a JSON-Lines–style array in
``.impactguard_feedback.json`` (configurable via the
``IMPACTGUARD_FEEDBACK`` environment variable or the *feedback_path*
argument).  Each entry is a dict with keys:

* ``patch_id`` – arbitrary identifier for the patch
* ``accepted`` – ``true``/``false``
* ``change_type`` – optional change category (e.g. ``"positional"``)
* ``recorded_at`` – ISO-8601 timestamp
* ``patch_data`` – optional free-form dict attached by the caller
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_FEEDBACK_PATH = ".impactguard_feedback.json"

# Weight keys that map to ``[impactguard.patches]`` config entries.
_WEIGHT_KEYS = [
    "structural_positional",
    "structural_kwarg",
    "structural_default",
    "semantic_required",
    "semantic_default",
    "complexity_multiline",
    "complexity_decorators",
    "complexity_annotations",
    "complexity_nested",
    "target_file_match",
    "target_name_only",
    "target_default",
]


def _resolve_path(feedback_path: str | None) -> str:
    """Return the effective feedback file path."""
    if feedback_path:
        return feedback_path
    return os.environ.get("IMPACTGUARD_FEEDBACK", DEFAULT_FEEDBACK_PATH)


def _is_safe_feedback_path(path: str) -> bool:
    """Return False and warn when *path* targets a system-sensitive location.

    Writes to well-known system directories (``/etc``, ``/usr``, ``/bin``,
    ``/sbin``, ``/lib``, ``/sys``, ``/proc``, ``/boot``, ``/dev``) are
    rejected to prevent accidental or injection-driven overwrites of system
    files.  All relative paths, temp-directory paths, and user home paths
    are allowed.

    Symlinks are resolved before checking so that a symlink pointing at a
    sensitive file cannot bypass the safety check.
    """
    p = Path(path)
    # Resolve symlinks so the check applies to the real target
    resolved = p.resolve()
    if not resolved.is_absolute():
        return True

    _SYSTEM_PREFIXES = (
        "/etc/",
        "/usr/",
        "/bin/",
        "/sbin/",
        "/lib/",
        "/lib64/",
        "/sys/",
        "/proc/",
        "/boot/",
        "/dev/",
    )
    norm = str(resolved)
    if any(norm.startswith(prefix) for prefix in _SYSTEM_PREFIXES) or norm in (
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/sys",
        "/proc",
        "/boot",
        "/dev",
    ):
        print(
            f"Warning: impactguard: feedback path '{path}' (resolved to "
            f"'{resolved}') targets a system directory; write rejected for safety.",
            file=sys.stderr,
        )
        return False
    return True


# ── Public API ────────────────────────────────────────────────────────────────


def record_outcome(
    patch_id: str,
    accepted: bool,
    change_type: str | None = None,
    patch_data: dict[str, Any] | None = None,
    feedback_path: str | None = None,
) -> None:
    """Record the outcome of a suggested patch.

    Args:
        patch_id: Arbitrary identifier for the patch (e.g. function name or
            UUID).
        accepted: ``True`` if the patch was accepted / applied, ``False``
            if rejected.
        change_type: Optional category string for the kind of change the
            patch addresses (e.g. ``"positional"``, ``"kwarg"``,
            ``"required"``).  Used for per-category weight calibration.
        patch_data: Optional free-form dict with extra context (e.g. the
            patch diff, confidence factors, etc.).
        feedback_path: Path to the feedback JSON file.  Uses the
            ``IMPACTGUARD_FEEDBACK`` environment variable or the default
            when *None*.
    """
    effective_path = _resolve_path(feedback_path)
    outcomes = _load_raw(effective_path)

    entry: dict[str, Any] = {
        "patch_id": patch_id,
        "accepted": accepted,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if change_type is not None:
        entry["change_type"] = change_type
    if patch_data is not None:
        entry["patch_data"] = patch_data

    outcomes.append(entry)
    _save_raw(effective_path, outcomes)


def load_outcomes(feedback_path: str | None = None) -> list[dict[str, Any]]:
    """Load all recorded patch outcomes.

    Args:
        feedback_path: Path to feedback JSON file.  Uses default when *None*.

    Returns:
        List of outcome dicts (most-recently-recorded last).
    """
    return _load_raw(_resolve_path(feedback_path))


def get_stats(feedback_path: str | None = None) -> dict[str, Any]:
    """Compute summary statistics from recorded outcomes.

    Args:
        feedback_path: Path to feedback JSON file.  Uses default when *None*.

    Returns:
        Dictionary with keys:

        * ``total``: total number of recorded outcomes
        * ``accepted``: count of accepted patches
        * ``rejected``: count of rejected patches
        * ``acceptance_rate``: fraction accepted (0.0–1.0)
        * ``by_change_type``: per-category acceptance rates
    """
    outcomes = load_outcomes(feedback_path)
    total = len(outcomes)
    accepted_count = sum(1 for o in outcomes if o.get("accepted"))
    rejected_count = total - accepted_count

    by_type: dict[str, dict[str, int]] = {}
    for o in outcomes:
        ct = o.get("change_type", "unknown")
        bucket = by_type.setdefault(ct, {"accepted": 0, "rejected": 0})
        if o.get("accepted"):
            bucket["accepted"] += 1
        else:
            bucket["rejected"] += 1

    by_type_rates: dict[str, float] = {}
    for ct, counts in by_type.items():
        tot = counts["accepted"] + counts["rejected"]
        by_type_rates[ct] = counts["accepted"] / tot if tot else 0.0

    return {
        "total": total,
        "accepted": accepted_count,
        "rejected": rejected_count,
        "acceptance_rate": accepted_count / total if total else 0.0,
        "by_change_type": by_type_rates,
    }


def compute_calibrated_weights(
    outcomes: list[dict[str, Any]],
) -> dict[str, float]:
    """Derive patch-confidence weights from acceptance-rate data.

    The calibration maps category acceptance rates onto the structural/semantic
    weight keys used by :mod:`patch_confidence`.  Categories are matched
    heuristically by name fragment (e.g. ``"positional"`` → updates
    ``structural_positional``).

    Args:
        outcomes: List of outcome dicts as returned by
            :func:`load_outcomes`.

    Returns:
        Dictionary of weight key → calibrated float value (0.0–1.0).
        Only keys with enough data (≥ 5 outcomes) are included.
    """
    # Bucket outcomes by change_type
    by_type: dict[str, list[bool]] = {}
    for o in outcomes:
        ct = o.get("change_type", "")
        if ct:
            by_type.setdefault(ct, []).append(bool(o.get("accepted")))

    calibrated: dict[str, float] = {}
    _MIN_SAMPLES = 5

    for ct, results in by_type.items():
        if len(results) < _MIN_SAMPLES:
            continue
        rate = sum(results) / len(results)
        ct_lower = ct.lower()
        # Map category name → config weight key(s)
        if "positional" in ct_lower:
            calibrated["structural_positional"] = max(0.1, rate)
        if "kwarg" in ct_lower:
            calibrated["structural_kwarg"] = max(0.1, rate)
        if "required" in ct_lower:
            calibrated["semantic_required"] = max(0.1, rate)
        if "optional" in ct_lower or "default" in ct_lower:
            calibrated["structural_default"] = max(0.1, rate)
        if "multiline" in ct_lower:
            calibrated["complexity_multiline"] = max(0.1, rate)

    return calibrated


def apply_weights_to_config(
    weights: dict[str, float],
    config_path: str = "impactguard.toml",
) -> bool:
    """Write calibrated weights back to ``impactguard.toml``.

    Only keys present in *weights* are updated; unrelated keys are left
    unchanged.  When the config file does not exist, a minimal one is
    created with only the ``[impactguard.patches]`` section.

    Args:
        weights: Calibrated weight dict from :func:`compute_calibrated_weights`.
        config_path: Path to the TOML config file.

    Returns:
        *True* on success, *False* when writing fails.
    """
    if not weights:
        return True

    if not _is_safe_feedback_path(config_path):
        print(
            "Error: impactguard: config path targets a system directory; "
            "write rejected for safety.",
            file=sys.stderr,
        )
        return False

    path = Path(config_path).resolve()
    # Read existing lines (preserve comments and other sections)
    existing_lines: list[str] = []
    if path.is_file():
        existing_lines = path.read_text().splitlines()

    # Locate the [impactguard.patches] section and update keys within it
    updated = _upsert_toml_section(existing_lines, "impactguard.patches", weights)

    try:
        path.write_text("\n".join(updated) + "\n")
        return True
    except OSError:
        return False


# ── Private helpers ───────────────────────────────────────────────────────────


def _load_raw(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(path: str, outcomes: list[dict[str, Any]]) -> None:
    if not _is_safe_feedback_path(path):
        return
    resolved = Path(path).resolve()
    resolved.write_text(json.dumps(outcomes, indent=2))


def _upsert_toml_section(
    lines: list[str],
    section_header: str,
    values: dict[str, float],
) -> list[str]:
    """Update or append key=value pairs inside a TOML section.

    If the section does not exist it is appended at the end of *lines*.
    Existing keys in the section are updated in-place; new keys are appended
    at the end of the section.
    """
    header = f"[{section_header}]"
    result = list(lines)

    # Find section start
    start_idx: int | None = None
    for i, line in enumerate(result):
        if line.strip() == header:
            start_idx = i
            break

    if start_idx is None:
        # Append the section at the end
        result.append("")
        result.append(header)
        for k, v in values.items():
            result.append(f"{k} = {v:.4f}")
        return result

    # Find section end (next section header or EOF)
    end_idx = len(result)
    for i in range(start_idx + 1, len(result)):
        stripped_line = result[i].strip()
        if stripped_line.startswith("[") and not stripped_line.startswith("[#"):
            end_idx = i
            break

    section_lines = result[start_idx + 1 : end_idx]
    remaining_values = dict(values)

    # Update existing keys
    for j, sline in enumerate(section_lines):
        stripped = sline.strip()
        for k in list(remaining_values.keys()):
            if stripped.startswith(k + " ") or stripped.startswith(k + "="):
                section_lines[j] = f"{k} = {remaining_values[k]:.4f}"
                del remaining_values[k]
                break

    # Append new keys not already present
    for k, v in remaining_values.items():
        section_lines.append(f"{k} = {v:.4f}")

    return result[: start_idx + 1] + section_lines + result[end_idx:]
