import inspect
import json
from collections import defaultdict
from functools import wraps

COUNTS = defaultdict(int)
DETAILS = {}


def trace(func):
    name = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            COUNTS[name] += 1
            if name not in DETAILS:
                sig = inspect.signature(func)
                bound = sig.bind_partial(*args, **kwargs)
                DETAILS[name] = {"args_count": len(args), "kwargs": list(kwargs.keys())}
        except Exception:
            pass

        return func(*args, **kwargs)

    return wrapper


def dump(path=".runtime_calls.json"):
    data = []
    for name, count in COUNTS.items():
        entry = {
            "function": name,
            "count": count,
        }
        entry.update(DETAILS.get(name, {}))
        data.append(entry)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def install_tracer(module, prefix=None):
    for name in dir(module):
        obj = getattr(module, name)

        if callable(obj) and hasattr(obj, "__module__"):
            if prefix and not obj.__module__.startswith(prefix):
                continue
            try:
                setattr(module, name, trace(obj))
            except Exception:
                pass
