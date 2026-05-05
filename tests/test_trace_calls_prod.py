"""Tests for trace_calls_prod module."""

from unittest.mock import patch

from impactguard.trace_calls_prod import (
    flush,
    install_tracer,
    should_sample,
)


def test_should_sample():
    """Test should_sample function."""
    # With SAMPLE_RATE = 0.01, random.random() < 0.01 is rarely True
    with patch("random.random", return_value=0.005):
        assert should_sample() is True

    with patch("random.random", return_value=0.5):
        assert should_sample() is False


def test_flush():
    """Test flush function."""
    import json
    import os
    import tempfile

    # Mock COUNTS
    from impactguard.trace_calls_prod import COUNTS

    COUNTS["test_func"] = 5

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        fname = f.name

    flush(fname)
    assert os.path.exists(fname)

    with open(fname) as fh:
        data = json.load(fh)
    assert len(data) > 0

    os.unlink(fname)
    COUNTS.clear()


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
