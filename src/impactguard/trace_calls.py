import inspect
import json
from collections import defaultdict
from collections.abc import Callable
from functools import wraps
from typing import Any

COUNTS: dict[str, int] = defaultdict(int)
DETAILS: dict[str, dict[str, Any]] = {}


def trace(func: Callable[..., Any]) -> Callable[..., Any]:
    name = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            COUNTS[name] += 1
            if name not in DETAILS:
                sig = inspect.signature(func)
                _ = sig.bind_partial(*args, **kwargs)  # noqa: F841 - called for side effects
                DETAILS[name] = {"args_count": len(args), "kwargs": list(kwargs.keys())}
        except Exception:
            pass

        return func(*args, **kwargs)

    return wrapper


def dump(path: str = ".runtime_calls.json") -> None:
    data = []  # noqa: F841
    for name, count in COUNTS.items():
        entry: dict[str, Any] = {
            "function": name,
            "count": count,
        }
        entry.update(DETAILS.get(name, {}))
        data.append(entry)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


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
