import sys
import json
import inspect
from functools import wraps

LOG = []

def trace(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            sig = inspect.signature(func)
            bound = sig.bind_partial(*args, **kwargs)

            LOG.append({
                "function": f"{func.__module__}.{func.__qualname__}",
                "args_count": len(args),
                "kwargs": list(kwargs.keys())
            })
        except Exception:
            pass

        return func(*args, **kwargs)

    return wrapper


def dump(path=".runtime_calls.json"):
    with open(path, "w") as f:
        json.dump(LOG, f, indent=2)


def install_tracer(module):
    for name in dir(module):
        obj = getattr(module, name)

        if callable(obj) and hasattr(obj, "__module__"):
            try:
                setattr(module, name, trace(obj))
            except Exception:
                pass
