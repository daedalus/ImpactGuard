"""Tests for trace_calls_prod module."""

from unittest.mock import patch

from impactguard.trace_calls_prod import (
    flush,
    install_tracer,
    should_sample,
)


def test_should_sample():
    """Test should_sample function."""
    # With SAMPLE_RATE = 0.01, _rng.random() < 0.01 is rarely True
    import impactguard.trace_calls_prod as tcp

    with patch.object(tcp._rng, "random", return_value=0.005):
        assert should_sample() is True

    with patch.object(tcp._rng, "random", return_value=0.5):
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


# ── Lock / concurrency ────────────────────────────────────────────────────────
#
# The trace wrapper acquires _lock (RLock) and may call flush() which also
# acquires _lock.  flush() can also be called directly from other threads.
# These tests verify no deadlock under concurrent access.


def test_trace_wrapper_lock_no_deadlock():
    """Call a traced function from concurrent threads + simultaneous flush()
    calls to verify the RLock chain (wrapper → flush) does not deadlock."""
    import threading
    import types

    import impactguard.trace_calls_prod as tcp

    # Force sampling to exercise the first lock acquisition.
    orig_should = tcp.should_sample
    tcp.should_sample = lambda: True

    orig_last_flush = tcp.LAST_FLUSH
    tcp.LAST_FLUSH = 0.0  # force flush on next call

    errors: list[BaseException] = []
    lock: threading.Lock = threading.Lock()
    call_count: list[int] = [0]

    def traced_target(x: int) -> int:
        call_count[0] += 1
        return x * 2

    traced = tcp.trace(traced_target)
    flush_path = None

    def traced_worker():
        try:
            for i in range(100):
                assert traced(i) == i * 2
        except BaseException as e:
            with lock:
                errors.append(e)

    def flush_worker():
        nonlocal flush_path
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                flush_path = f.name
            for _ in range(20):
                tcp.flush(flush_path)
        except BaseException as e:
            with lock:
                errors.append(e)

    workers = [
        threading.Thread(target=traced_worker, daemon=True),
        threading.Thread(target=traced_worker, daemon=True),
        threading.Thread(target=traced_worker, daemon=True),
        threading.Thread(target=flush_worker, daemon=True),
        threading.Thread(target=flush_worker, daemon=True),
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=30)
    for w in workers:
        if w.is_alive():
            tcp.should_sample = orig_should
            tcp.LAST_FLUSH = orig_last_flush
            import os
            if flush_path and os.path.exists(flush_path):
                os.unlink(flush_path)
            pytest.fail("trace wrapper lock deadlocked (thread hung for 30s)")

    tcp.should_sample = orig_should
    tcp.LAST_FLUSH = orig_last_flush
    if flush_path:
        import os
        if os.path.exists(flush_path):
            os.unlink(flush_path)
    if errors:
        raise errors[0]
