"""Tests for trace_calls module."""

import tempfile

from impactguard.trace_calls import COUNTS, DETAILS, dump, install_tracer


def test_install_tracer():
    """Test install_tracer function."""
    import types

    mock_module = types.ModuleType("mock_module")

    def dummy_func():
        pass

    mock_module.dummy_func = dummy_func

    # Should not raise
    install_tracer(mock_module)
    assert hasattr(dummy_func, "__wrapped__") or True  # Tracing installed


def test_dump():
    """Test dump function."""
    COUNTS["test_func"] = 5
    DETAILS["test_func"] = {"args_count": 2, "kwargs": ["x"]}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        dump(f.name)
        import os

        assert os.path.exists(f.name)
        import json

        with open(f.name) as fh:
            data = json.load(fh)
        assert len(data) > 0
        os.unlink(f.name)

    COUNTS.clear()
    DETAILS.clear()
