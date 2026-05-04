"""
Example conftest.py for pytest integration with ImpactGuard runtime tracing.

Place this in your project's test directory and adjust the mypackage import
to point to the package you want to trace.
"""

import trace_calls
import sys
import os

# Adjust this import to point to your actual package
# import mypackage

def pytest_sessionstart(session):
    """Install tracers before tests run."""
    # Uncomment and adjust:
    # trace_calls.install_tracer(mypackage)
    pass

def pytest_sessionfinish(session, exitstatus):
    """Dump runtime calls after tests complete."""
    output_path = os.path.join(os.getcwd(), ".runtime_calls.json")
    trace_calls.dump(output_path)
    print(f"\n[ImpactGuard] Runtime calls dumped to {output_path}")
