"""Shared test fixtures for ImpactGuard tests."""

import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Robustness Evaluator — wired to pytest hooks
# ---------------------------------------------------------------------------

# Maps normalised class-name fragments to adversarial taxonomy category names.
_TAXONOMY_CLASS_MAP: dict[str, str] = {
    "boundaryedgecases": "boundary",
    "semanticperturbation": "semantic",
    "evasionobfuscation": "evasion",
    "compositionalattacks": "compositional",
}

# Per-session counters, populated by pytest_runtest_logreport.
_outcomes: dict = {
    "adv": {"total": 0, "passed": 0},
    "norm": {"total": 0, "passed": 0},
    "categories": {},  # category -> {"total": int, "passed": int}
}


def _classify(nodeid: str) -> tuple[bool, Optional[str]]:
    """Return (is_adversarial, category_or_None) for a test node ID.

    A test is adversarial when "adversarial" appears (case-insensitive) in
    the file path or the class name portion of the node ID.

    The category is derived from the class name using *_TAXONOMY_CLASS_MAP*;
    it is only returned for adversarial tests that belong to a known category.
    """
    parts = nodeid.split("::")
    file_part = parts[0].lower()
    cls_part = parts[1].lower() if len(parts) >= 3 else ""

    is_adv = "adversarial" in file_part or "adversarial" in cls_part

    # Strip non-alpha chars for map lookup (handles CamelCase → key).
    # Also strip a leading "test" prefix that pytest class names commonly carry
    # (e.g. "TestBoundaryEdgeCases" → "boundaryedgecases").
    cls_key = "".join(c for c in cls_part if c.isalpha())
    if cls_key.startswith("test"):
        cls_key = cls_key[len("test"):]
    category = _TAXONOMY_CLASS_MAP.get(cls_key) if is_adv else None

    return is_adv, category


def pytest_runtest_logreport(report: pytest.TestReport) -> None:  # noqa: V103
    """Collect pass/fail counts, split by adversarial vs. normal."""
    if report.when != "call":
        return

    is_adv, category = _classify(report.nodeid)
    passed = report.passed

    bucket = _outcomes["adv"] if is_adv else _outcomes["norm"]
    bucket["total"] += 1
    if passed:
        bucket["passed"] += 1

    if is_adv and category:
        cat = _outcomes["categories"].setdefault(category, {"total": 0, "passed": 0})
        cat["total"] += 1
        if passed:
            cat["passed"] += 1


def _read_coverage() -> float:
    """Return total line-coverage as a ratio in [0.0, 1.0].

    Attempts to load the `.coverage` data file written by *pytest-cov*.
    Returns 1.0 when the file is absent or unreadable so that the robustness
    score is not artificially suppressed in coverage-less runs.
    """
    try:
        import coverage as cov_module  # pytest-cov installs coverage

        cov = cov_module.Coverage()
        cov.load()
        buf = io.StringIO()
        pct = cov.report(file=buf)
        return max(0.0, min(1.0, pct / 100.0))
    except Exception:  # noqa: BLE001
        return 1.0


def pytest_terminal_summary(  # noqa: V103
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,  # noqa: F841
    config: pytest.Config,  # noqa: ARG001
) -> None:
    """Compute and display the Robustness Evaluation report at the end of the session."""
    adv = _outcomes["adv"]
    norm = _outcomes["norm"]
    n_total = adv["total"] + norm["total"]

    if n_total == 0:
        return

    # Import the evaluator from tools/ (project root / tools).
    tools_dir = Path(__file__).parent.parent / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from robustness_evaluator import (  # type: ignore[import]
        CategoryStats,
        evaluate_robustness,
        format_report,
    )

    coverage_ratio = _read_coverage()

    cats = [
        CategoryStats(name=name, total=stats["total"], passing=stats["passed"])
        for name, stats in _outcomes["categories"].items()
    ]

    try:
        result = evaluate_robustness(
            n_total=n_total,
            n_adversarial=adv["total"],
            passing_adv=adv["passed"],
            passing_norm=norm["passed"],
            coverage=coverage_ratio,
            categories=cats if cats else None,
        )
    except ValueError as exc:
        terminalreporter.write_line(f"[robustness evaluator] skipped: {exc}")
        return

    terminalreporter.write_sep("=", "Robustness Evaluation")
    terminalreporter.write_line(format_report(result))


@pytest.fixture
def sample_signature_data():
    """Provide sample signature data for tests."""
    return [
        {
            "fqname": "src/module.py:func_one",
            "name": "func_one",
            "file": "src/module.py",
            "lineno": 10,
            "end_lineno": 15,
            "positional": [
                {"name": "arg1", "has_default": False},
                {"name": "arg2", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
        {
            "fqname": "src/module.py:func_two",
            "name": "func_two",
            "file": "src/module.py",
            "lineno": 20,
            "end_lineno": 25,
            "positional": [],
            "kwonly": [],
            "vararg": True,
            "kwarg": False,
        },
    ]


@pytest.fixture  # noqa: V103
def sample_signatures_file(sample_signature_data):
    """Create a temporary signatures JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample_signature_data, f)
        return f.name


@pytest.fixture  # noqa: V103
def sample_python_file():
    """Create a temporary Python file with functions."""
    content = '''
def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"

async def async_func(data: list) -> dict:
    """Process data asynchronously."""
    return {"result": data}

class MyClass:
    def method(self, x: int) -> int:
        return x * 2
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture  # noqa: V103
def empty_python_file():
    """Create an empty Python file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("# Empty file\n")
        return f.name


@pytest.fixture
def runtime_data():
    """Provide sample runtime data."""
    return [
        {"function": "src/module.py:func_one", "count": 42},
        {"function": "src/module.py:func_two", "count": 10},
    ]


@pytest.fixture  # noqa: V103
def runtime_data_file(runtime_data):
    """Create a temporary runtime data JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(runtime_data, f)
        return f.name
