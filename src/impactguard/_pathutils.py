"""Internal path-validation utilities shared across ImpactGuard modules.

These helpers are intentionally kept private (leading underscore) and are
*not* part of the public API.  They exist solely to centralise security-
sensitive validation logic so it cannot diverge between call sites.
"""

from pathlib import Path


def is_safe_path(file: str) -> bool:
    """Return *True* only when *file* is a safe relative path with no traversal.

    A path is considered safe when it:

    * is non-empty
    * is not absolute
    * contains no path-traversal (``..``) components

    This check is intentionally conservative: it is used before opening files
    whose paths originate from JSON inputs that may be attacker-controlled.

    Note:
        This function is Unix-centric.  Absolute Windows paths (e.g.,
        ``C:\\Windows\\System32``) are rejected by the ``is_absolute()`` check
        but UNC paths (``\\\\server\\share``) are not explicitly handled.

    Args:
        file: Candidate file path string.

    Returns:
        *True* if the path is safe to open, *False* otherwise.
    """
    if not file:
        return False
    p = Path(file)
    # Reject absolute paths and path-traversal sequences.
    if p.is_absolute() or ".." in p.parts:
        return False
    return True
