import json
import random
import time
from collections import defaultdict
from collections.abc import Callable
from functools import wraps
from typing import Any

SAMPLE_RATE = 0.01  # 1% of calls
FLUSH_INTERVAL = 10  # seconds

COUNTS: dict[str, int] = defaultdict(int)
LAST_FLUSH = time.time()


def should_sample() -> bool:
    return random.random() < SAMPLE_RATE


def trace(func: Callable[..., Any]) -> Callable[..., Any]:
    name = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        global LAST_FLUSH

        if should_sample():
            COUNTS[name] += 1

        # periodic flush (non-blocking-ish)
        now = time.time()
        if now - LAST_FLUSH > FLUSH_INTERVAL:
            try:
                flush()
            except Exception:
                pass
            LAST_FLUSH = now

        return func(*args, **kwargs)

    return wrapper


def flush(path: str = "/tmp/runtime_calls.json") -> None:
    data = dict(COUNTS)

    with open(path, "w") as f:
        json.dump(data, f)

    COUNTS.clear()


def install_tracer(module: object, prefix: str | None = None) -> None:
    for name in dir(module):
        obj = getattr(module, name)

        if callable(obj) and hasattr(obj, "__module__"):
            if prefix and not obj.__module__.startswith(prefix):
                continue
            try:
                setattr(module, name, trace(obj))
            except Exception:
                pass
