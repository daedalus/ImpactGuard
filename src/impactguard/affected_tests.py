"""Affected test file detection.

Uses the persisted call graph's ``file_imports`` table to find test
files that transitively depend on changed source files.
"""

from typing import Any

from ._logging import get_logger

_log = get_logger(__name__)

_TEST_PATTERNS = (
    "test_",
    "_test",
    ".spec.",
    ".test.",
    "/tests/",
    "/__tests__/",
    "/e2e/",
    "/spec/",
    "/test_",
    "_test.py",
    "_spec.",
)


def _is_test_file(file_path: str) -> bool:
    lp = file_path.lower()
    for pat in _TEST_PATTERNS:
        if pat in lp:
            return True
    return False


def get_affected_tests(
    cg_db: Any, changed_files: list[str], depth: int = 5
) -> list[str]:
    """Find test files transitively affected by *changed_files*.

    Args:
        cg_db: A ``CallGraphDB`` instance (must have ``get_affected_tests``).
        changed_files: Source file paths that were changed.
        depth: Maximum BFS depth for transitive dependency traversal.

    Returns:
        Sorted list of test file paths.
    """
    return cg_db.get_affected_tests(changed_files, depth=depth)


def describe_affected_tests(
    cg_db: Any, changed_files: list[str], depth: int = 5
) -> dict[str, object]:
    """Return a structured report of affected tests.

    Args:
        cg_db: A ``CallGraphDB`` instance.
        changed_files: Source file paths that were changed.
        depth: Maximum BFS depth.

    Returns:
        Dict with keys:
            - changed_files: input list
            - affected_tests: sorted list of test file paths
            - test_count: number of affected test files
            - traversal_depth: depth used
    """
    tests = get_affected_tests(cg_db, changed_files, depth=depth)
    return {
        "changed_files": changed_files,
        "affected_tests": tests,
        "test_count": len(tests),
        "traversal_depth": depth,
    }
