"""Internal path-validation utilities shared across ImpactGuard modules.

These helpers are intentionally kept private (leading underscore) and are
*not* part of the public API.  They exist solely to centralise security-
sensitive validation logic so it cannot diverge between call sites.
"""

from pathlib import PurePosixPath, PureWindowsPath


def is_safe_path(file: str) -> bool:
    """Return *True* only when *file* is a safe relative path with no traversal.

    A path is considered safe when it:

    * is non-empty
    * contains no null bytes
    * is not absolute on either POSIX or Windows
    * contains no path-traversal (``..``) components under either separator style
    * contains no Windows drive prefix or UNC/share root

    This check is intentionally conservative: it is used before opening files
    whose paths originate from JSON inputs that may be attacker-controlled.

    Args:
        file: Candidate file path string.

    Returns:
        *True* if the path is safe to open, *False* otherwise.
    """
    if not file or "\x00" in file:
        return False

    posix_path = PurePosixPath(file)
    windows_path = PureWindowsPath(file)

    if posix_path.is_absolute() or ".." in posix_path.parts:
        return False

    # Reject Windows absolute/drive/UNC paths and traversal encoded with
    # backslash separators even when running on non-Windows hosts.
    if windows_path.drive or windows_path.root or ".." in windows_path.parts:
        return False
    return True
