"""Historical baseline storage for ImpactGuard.

Provides save / load / compare operations so that signature snapshots can
persist across CI runs and branch switches.  The default storage path is
``.impactguard_baseline.json`` in the current working directory; this can be
overridden via the *path* argument or the ``IMPACTGUARD_BASELINE`` environment
variable.
"""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_BASELINE_PATH = ".impactguard_baseline.json"


def _resolve_path(path: str | None) -> str:
    """Return the effective baseline file path."""
    if path:
        return path
    return os.environ.get("IMPACTGUARD_BASELINE", DEFAULT_BASELINE_PATH)


def save_baseline(
    files: list[str],
    path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Extract signatures from *files* and save them as the new baseline.

    Args:
        files: Python source files to snapshot.
        path: Output path for the baseline JSON.  Defaults to
            ``IMPACTGUARD_BASELINE`` env-var or ``.impactguard_baseline.json``.
        metadata: Optional dict of extra fields (e.g. git SHA, timestamp) to
            store alongside the signatures for audit purposes.

    Returns:
        Absolute path to the saved baseline file.
    """
    from .extract_signatures import extract

    effective_path = _resolve_path(path)
    signatures = extract(files)

    payload: dict[str, Any] = {"signatures": signatures}
    if metadata:
        payload["metadata"] = metadata

    with open(effective_path, "w") as f:
        json.dump(payload, f, indent=2)

    return str(Path(effective_path).resolve())


def load_baseline(path: str | None = None) -> dict[str, Any]:
    """Load a previously saved baseline.

    Args:
        path: Path to the baseline JSON.  Uses env-var / default if *None*.

    Returns:
        Dictionary with ``"signatures"`` list and optional ``"metadata"``.

    Raises:
        FileNotFoundError: When the baseline file does not exist.
        ValueError: When the file cannot be parsed.
    """
    effective_path = _resolve_path(path)
    p = Path(effective_path)
    if not p.is_file():
        raise FileNotFoundError(
            f"Baseline not found: {effective_path}. "
            "Run `impactguard baseline save` first."
        )
    try:
        with open(effective_path) as f:
            data: dict[str, Any] = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot parse baseline file: {effective_path}") from exc

    # Support both wrapped {"signatures": [...]} and bare [...] formats
    if isinstance(data, list):
        return {"signatures": data}
    return data


def compare_with_baseline(
    new_files: list[str],
    baseline_path: str | None = None,
    include_private: bool | None = None,
) -> dict[str, Any]:
    """Compare *new_files* against the stored baseline.

    Args:
        new_files: Python source files representing the *new* version.
        baseline_path: Path to baseline JSON.  Uses default when *None*.
        include_private: Whether to include private (``_``-prefixed) symbols.

    Returns:
        Dictionary with keys:
            * ``"comparison"``: breaking / nonbreaking change lists
            * ``"semver"``: suggested semver bump
            * ``"baseline_metadata"``: metadata from the baseline file (if any)
    """
    import tempfile

    from .extract_signatures import extract
    from .compare_signatures import compare
    from .semver import format_semver_recommendation

    baseline = load_baseline(baseline_path)
    old_sigs = baseline["signatures"]

    new_sigs = extract(new_files)

    with tempfile.TemporaryDirectory() as tmpdir:
        old_path = Path(tmpdir) / "old.json"
        new_path = Path(tmpdir) / "new.json"
        old_path.write_text(json.dumps(old_sigs))
        new_path.write_text(json.dumps(new_sigs))

        comparison = compare(str(old_path), str(new_path), include_private=include_private)

    return {
        "comparison": comparison,
        "semver": format_semver_recommendation(comparison),
        "baseline_metadata": baseline.get("metadata"),
    }


def baseline_exists(path: str | None = None) -> bool:
    """Return *True* if a baseline file exists at *path* (or the default)."""
    return Path(_resolve_path(path)).is_file()
