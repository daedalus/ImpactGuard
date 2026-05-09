"""
Example conftest.py for pytest integration with ImpactGuard runtime tracing.

Place this in your project's test directory and adjust the mypackage import
to point to the package you want to trace.
"""

import os

import trace_calls

# Adjust this import to point to your actual package
# import mypackage


def pytest_sessionstart(_session: object) -> None:  # noqa: V103
    """Install tracers before tests run."""
    # Uncomment and adjust:
    # trace_calls.install_tracer(mypackage)
    pass


def pytest_sessionfinish(_session: object, _exitstatus: int) -> None:  # noqa: V103
    """Dump runtime calls after tests complete."""
    output_path = os.path.join(os.getcwd(), ".runtime_calls.json")
    trace_calls.dump(output_path)
    print(f"\n[ImpactGuard] Runtime calls dumped to {output_path}")
