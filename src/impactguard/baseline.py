"""Historical baseline storage for ImpactGuard.

Provides save / load / compare operations so that signature snapshots can
persist across CI runs and branch switches.  The default storage path is
``.impactguard_baseline.json`` in the current working directory; this can be
overridden via the *path* argument or the ``IMPACTGUARD_BASELINE`` environment
variable.

Multi-baseline / release history
---------------------------------
Tagged baselines are stored as a JSON object keyed by tag string inside
``.impactguard_history.json`` (or ``IMPACTGUARD_HISTORY`` env-var).  This
allows comparing against any historical release snapshot.
"""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_BASELINE_PATH = ".impactguard_baseline.json"
DEFAULT_HISTORY_PATH = ".impactguard_history.json"


def _resolve_path(path: str | None) -> str:
    """Return the effective baseline file path."""
    if path:
        return path
    return os.environ.get("IMPACTGUARD_BASELINE", DEFAULT_BASELINE_PATH)


def _resolve_history_path(path: str | None) -> str:
    """Return the effective history file path."""
    if path:
        return path
    return os.environ.get("IMPACTGUARD_HISTORY", DEFAULT_HISTORY_PATH)


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

    from .compare_signatures import compare
    from .extract_signatures import extract
    from .semver import format_semver_recommendation

    baseline = load_baseline(baseline_path)
    old_sigs = baseline["signatures"]

    new_sigs = extract(new_files)

    with tempfile.TemporaryDirectory() as tmpdir:
        old_path = Path(tmpdir) / "old.json"
        new_path = Path(tmpdir) / "new.json"
        old_path.write_text(json.dumps(old_sigs))
        new_path.write_text(json.dumps(new_sigs))

        comparison = compare(
            str(old_path), str(new_path), include_private=include_private
        )

    return {
        "comparison": comparison,
        "semver": format_semver_recommendation(comparison),
        "baseline_metadata": baseline.get("metadata"),
    }


def baseline_exists(path: str | None = None) -> bool:
    """Return *True* if a baseline file exists at *path* (or the default)."""
    return Path(_resolve_path(path)).is_file()


# ── Multi-baseline / Release history ─────────────────────────────────────────


def save_tagged_baseline(
    tag: str,
    files: list[str],
    history_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Save a tagged snapshot to the release-history store.

    Multiple snapshots are accumulated in a single JSON file keyed by *tag*,
    allowing later comparison against any historical release.

    Args:
        tag: Release identifier, e.g. ``"v1.2.0"`` or ``"2024-Q1"``.
        files: Python source files to snapshot.
        history_path: Path to the history JSON file.  Uses the
            ``IMPACTGUARD_HISTORY`` env-var or the default when *None*.
        metadata: Optional extra fields stored alongside the snapshot.

    Returns:
        Absolute path to the history file.

    Raises:
        ValueError: When *tag* is empty.
    """
    from .extract_signatures import extract

    if not tag:
        raise ValueError("tag must be a non-empty string")

    effective_path = _resolve_history_path(history_path)
    history = _load_history(effective_path)

    signatures = extract(files)
    entry: dict[str, Any] = {"signatures": signatures}
    if metadata:
        entry["metadata"] = metadata

    history[tag] = entry
    Path(effective_path).write_text(json.dumps(history, indent=2))
    return str(Path(effective_path).resolve())


def load_tagged_baseline(
    tag: str,
    history_path: str | None = None,
) -> dict[str, Any]:
    """Load a specific tagged snapshot from the history store.

    Args:
        tag: Release identifier previously passed to
            :func:`save_tagged_baseline`.
        history_path: Path to history JSON file.  Uses default when *None*.

    Returns:
        Dictionary with ``"signatures"`` list and optional ``"metadata"``.

    Raises:
        FileNotFoundError: When the history file does not exist.
        KeyError: When *tag* is not present in the history.
    """
    effective_path = _resolve_history_path(history_path)
    if not Path(effective_path).is_file():
        raise FileNotFoundError(
            f"History file not found: {effective_path}. "
            "Run `impactguard baseline save --tag <tag>` first."
        )
    history = _load_history(effective_path)
    if tag not in history:
        available = sorted(history.keys())
        raise KeyError(f"Tag '{tag}' not found in history. Available tags: {available}")
    return history[tag]  # type: ignore[no-any-return]


def list_baselines(history_path: str | None = None) -> list[dict[str, Any]]:
    """List all tagged snapshots stored in the history file.

    Args:
        history_path: Path to history JSON file.  Uses default when *None*.

    Returns:
        List of dicts with ``"tag"`` and ``"metadata"`` keys, sorted by tag.
        Returns an empty list when no history file exists.
    """
    effective_path = _resolve_history_path(history_path)
    if not Path(effective_path).is_file():
        return []
    history = _load_history(effective_path)
    return [
        {
            "tag": tag,
            "signature_count": len(entry.get("signatures", [])),
            "metadata": entry.get("metadata"),
        }
        for tag, entry in sorted(history.items())
    ]


def compare_with_tagged_baseline(
    tag: str,
    new_files: list[str],
    history_path: str | None = None,
    include_private: bool | None = None,
) -> dict[str, Any]:
    """Compare *new_files* against a tagged historical snapshot.

    Args:
        tag: Release tag identifying the baseline to compare against.
        new_files: Python source files representing the *new* version.
        history_path: Path to history JSON file.  Uses default when *None*.
        include_private: Whether to include private symbols.

    Returns:
        Same format as :func:`compare_with_baseline`.
    """
    import tempfile

    from .compare_signatures import compare
    from .extract_signatures import extract
    from .semver import format_semver_recommendation

    entry = load_tagged_baseline(tag, history_path)
    old_sigs = entry["signatures"]
    new_sigs = extract(new_files)

    with tempfile.TemporaryDirectory() as tmpdir:
        old_path = Path(tmpdir) / "old.json"
        new_path = Path(tmpdir) / "new.json"
        old_path.write_text(json.dumps(old_sigs))
        new_path.write_text(json.dumps(new_sigs))
        comparison = compare(
            str(old_path), str(new_path), include_private=include_private
        )

    return {
        "comparison": comparison,
        "semver": format_semver_recommendation(comparison),
        "baseline_tag": tag,
        "baseline_metadata": entry.get("metadata"),
    }


def delete_tagged_baseline(
    tag: str,
    history_path: str | None = None,
) -> bool:
    """Remove a tagged snapshot from the history store.

    Args:
        tag: Tag to delete.
        history_path: Path to history JSON file.  Uses default when *None*.

    Returns:
        *True* if the tag was found and removed, *False* if it did not exist.
    """
    effective_path = _resolve_history_path(history_path)
    if not Path(effective_path).is_file():
        return False
    history = _load_history(effective_path)
    if tag not in history:
        return False
    del history[tag]
    Path(effective_path).write_text(json.dumps(history, indent=2))
    return True


# ── Private helpers ───────────────────────────────────────────────────────────


def _load_history(path: str) -> dict[str, Any]:
    """Load the history JSON file, returning an empty dict on missing/corrupt file."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}
