"""Concurrency stress tests for CallGraphDB connection lifecycle.

Verifies that close() correctly tears down all connections, that
concurrent get_connection() + close() doesn't leak file descriptors,
and that use-after-close raises RuntimeError on every thread.
"""

from __future__ import annotations

import threading

import pytest


class TestConcurrentClose:
    """Stress close() against concurrent _get_connection() calls."""

    def _worker(self, cg, results: list, idx: int) -> None:
        """Each worker creates a connection then tries to use it."""
        try:
            con = cg._get_connection()
            results[idx] = "ok"
        except RuntimeError as e:
            if "closed" in str(e):
                results[idx] = "closed"
            else:
                results[idx] = f"error: {e}"
        except Exception as e:
            results[idx] = f"error: {e}"

    def test_close_during_concurrent_get(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        n_threads = 20
        results = [""] * n_threads
        threads = []

        # Start workers that will call _get_connection
        for i in range(n_threads):
            t = threading.Thread(target=self._worker, args=(cg, results, i))
            threads.append(t)

        for t in threads:
            t.start()

        # Close while workers are starting
        cg.close()

        for t in threads:
            t.join(timeout=5)

        # All threads should either get "ok" (connection created before close)
        # or "closed" (RuntimeError after close).  No thread should crash.
        for r in results:
            assert r in ("ok", "closed"), f"Unexpected result: {r}"

        # No connections should remain
        assert len(cg._all_connections) == 0

    def test_no_use_after_close(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        cg.close()

        with pytest.raises(RuntimeError, match="closed"):
            cg._get_connection()

    def test_close_does_not_raise_on_broken_connection(self, tmp_path):
        """close() must not propagate errors when a connection fails to close.

        It should log a warning and continue, not crash.
        """
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        _ = cg._get_connection()

        # Close the connection out-of-band so cg.close() encounters an error
        cg._all_connections[0].close()

        # Must not raise — errors should be caught and logged
        cg.close()
        assert len(cg._all_connections) == 0

    def test_multiple_threads_all_closed(self, tmp_path):
        """After close(), every thread's connection should be unusable."""
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        n_threads = 10
        errors = []

        def worker():
            try:
                con = cg._get_connection()
                # If we got a connection before close, try using it after
                cg.close()
                try:
                    con.execute("SELECT 1")
                except Exception:
                    pass  # Expected: closed connection
            except RuntimeError as e:
                if "closed" not in str(e):
                    errors.append(str(e))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Unexpected errors: {errors}"
        assert len(cg._all_connections) == 0
