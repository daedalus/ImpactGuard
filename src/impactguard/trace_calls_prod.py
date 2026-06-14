"""Production runtime call tracer (Python-only).

Sampling call tracer for production environments.  Uses a configurable
sample rate, periodic flush, and signal-safe shutdown.

.. note::

   This module is **Python-only**.  It relies on CPython-specific
   ``__module__``, ``__qualname__``, and ``@functools.wraps``.
   Non-Python languages must supply runtime observations externally
   as a JSON file matching the schema documented in ``SPEC.md``.
"""

import json
import os
import random
import signal
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from functools import wraps
from typing import Any

from ._logging import get_logger

_log = get_logger(__name__)

SAMPLE_RATE = 0.01  # 1% of calls
FLUSH_INTERVAL = 10  # seconds

_lock = threading.RLock()
COUNTS: dict[str, int] = defaultdict(int)
LAST_FLUSH = time.time()

# Signal-safe flush request flag.  Set by SIGTERM handler, drained on the next
# sampled call so flush() runs from normal execution context (avoiding lock
# re-entrancy hazards in signal handlers).
_flush_requested = False

# Use a dedicated Random instance rather than the module-level shared state.
# random.random() delegates to a module-level instance whose internal state is
# shared across all threads; under heavy concurrent use the GIL prevents data
# corruption but can cause non-uniform sampling distributions.  A private
# instance avoids this without requiring per-call locking.
_rng = random.Random()


def _signal_handler(signum: int, frame: object) -> None:  # noqa: ARG001
    global _flush_requested
    _flush_requested = True


def set_seed(seed: int) -> None:
    """Seed the sampler's RNG for deterministic behaviour (e.g. in tests)."""
    _rng.seed(seed)


set_seed(42)


def should_sample() -> bool:
    return _rng.random() < SAMPLE_RATE


def trace(func: Callable[..., Any]) -> Callable[..., Any]:
    name = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        global LAST_FLUSH, _flush_requested

        if should_sample():
            with _lock:
                COUNTS[name] += 1

        # periodic flush (also drains signal-requested flushes)
        with _lock:
            now = time.time()
            if _flush_requested or (now - LAST_FLUSH > FLUSH_INTERVAL):
                _flush_requested = False
                try:
                    flush()
                except OSError:
                    _log.debug("Failed to flush trace data")
                LAST_FLUSH = now

        return func(*args, **kwargs)

    return wrapper


def flush(path: str | None = None) -> None:
    import fcntl
    import tempfile

    if path is None:
        path = ".runtime_calls.json"

    with _lock:
        data = dict(COUNTS)
        COUNTS.clear()

    dir_name = os.path.dirname(os.path.abspath(path)) or "."
    lock_path = path + ".lock"

    # Read-merge-write under an fcntl flock so that multiple processes (e.g.
    # gunicorn workers) can safely flush without clobbering each other.
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            existing: dict[str, int] = {}
            try:
                with open(path) as f:
                    existing = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                _log.debug("No existing trace data to merge from '%s'", path)

            for k, v in data.items():
                existing[k] = existing.get(k, 0) + v

            with tempfile.NamedTemporaryFile(
                mode="w", dir=dir_name, delete=False, suffix=".json"
            ) as f:
                json.dump(existing, f)
                temp_path = f.name

            os.replace(temp_path, path)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


import atexit as _atexit

_atexit.register(flush)

# Best-effort SIGTERM handler — sets a flag drained on the next sampled call.
# Chains with any existing handler so the app's own handler is not replaced.
_try_sigterm = True
_existing_sigterm = None
try:
    _existing_sigterm = signal.getsignal(signal.SIGTERM)
except (ValueError, OSError):
    _try_sigterm = False


def _sigterm_chain(signum: int, frame: object) -> None:
    _signal_handler(signum, frame)
    if _existing_sigterm is not None and callable(_existing_sigterm):
        _existing_sigterm(signum, frame)


if _try_sigterm:
    try:
        signal.signal(signal.SIGTERM, _sigterm_chain)
    except (ValueError, OSError):
        _log.debug("Failed to register SIGTERM handler for trace cleanup")


def install_tracer(module: object, prefix: str | None = None) -> None:
    for name in dir(module):
        obj = getattr(module, name)

        if callable(obj) and hasattr(obj, "__module__"):
            if prefix and not obj.__module__.startswith(prefix):
                continue
            try:
                setattr(module, name, trace(obj))
            except (AttributeError, TypeError):
                _log.debug("Cannot trace attribute %s on module", name)
