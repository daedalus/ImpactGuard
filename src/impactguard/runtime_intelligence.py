from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._logging import get_logger

_log = get_logger(__name__)

_RUNTIME_NAME_KEYS = ("function", "fqname", "symbol", "name", "callee", "target", "id")
_RUNTIME_COUNT_KEYS = ("count", "calls", "samples", "hits", "invocations")
_RUNTIME_ARGC_KEYS = ("args_count", "argc", "arity")
_RUNTIME_KWARGS_KEYS = ("kwargs", "keywords")
_RUNTIME_CONTAINER_KEYS = ("runtime", "observations", "entries", "functions")


def _coerce_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return None


def _coerce_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name or None


def canonical_runtime_name(name: str) -> str:
    """Convert a language-specific runtime symbol into a dot-normalized key."""
    normalized = name.strip().replace("\\", "/").replace("::", ".").replace("#", ".")
    if not normalized:
        return ""

    if "://" in normalized:
        return normalized

    if ":" in normalized:
        file_part, symbol_part = normalized.split(":", 1)
        suffix = Path(file_part).suffix
        if suffix:
            file_part = file_part[: -len(suffix)]
        normalized = f"{file_part.replace('/', '.')}.{symbol_part}"

    normalized = normalized.replace("/", ".")
    while ".." in normalized:
        normalized = normalized.replace("..", ".")
    return normalized.strip(".")


def runtime_name_variants(name: str) -> list[str]:
    """Return stable aliases for matching runtime observations to signatures."""
    raw = _coerce_name(name)
    if raw is None:
        return []

    variants = {raw}
    canonical = canonical_runtime_name(raw)
    if canonical:
        variants.add(canonical)
        parts = [part for part in canonical.split(".") if part]
        if len(parts) >= 2:
            variants.add(".".join(parts[-2:]))
        tail = canonical.rsplit(".", 1)[-1]
        if tail:
            variants.add(tail)

    if ":" in raw and ("/" in raw or bool(Path(raw.split(":", 1)[0]).suffix)):
        file_part, symbol_part = raw.split(":", 1)
        symbol = symbol_part.replace("::", ".").replace("#", ".").strip(".")
        if symbol:
            variants.add(symbol)
            stem = Path(file_part).stem
            if stem:
                variants.add(f"{stem}.{symbol}")

    return sorted(v for v in variants if v)


def _coerce_kwargs(value: object) -> list[str] | None:
    if isinstance(value, dict):
        return [str(key) for key in value.keys()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return None


def _first_not_none[T](values: list[T | None]) -> T | None:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_runtime_entry(entry: object) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None

    name = _first_not_none([_coerce_name(entry.get(key)) for key in _RUNTIME_NAME_KEYS])
    if name is None:
        return None

    count = _first_not_none(
        [_coerce_non_negative_int(entry.get(key)) for key in _RUNTIME_COUNT_KEYS]
    )
    args_count = _first_not_none(
        [_coerce_non_negative_int(entry.get(key)) for key in _RUNTIME_ARGC_KEYS]
    )
    kwargs = _first_not_none(
        [_coerce_kwargs(entry.get(key)) for key in _RUNTIME_KWARGS_KEYS]
    )

    normalized: dict[str, Any] = {
        "function": name,
        "count": count if count is not None else 1,
        "canonical": canonical_runtime_name(name),
        "aliases": runtime_name_variants(name),
    }

    if args_count is not None:
        normalized["args_count"] = args_count
    if kwargs is not None:
        normalized["kwargs"] = kwargs

    language = entry.get("language")
    if isinstance(language, str) and language.strip():
        normalized["language"] = language.strip()

    return normalized


def _normalize_dict_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a dict-shaped runtime payload (list container or nested dict)."""
    for key in _RUNTIME_CONTAINER_KEYS:
        nested = data.get(key)
        if isinstance(nested, list):
            return normalize_runtime_payload(nested)

    direct = _normalize_runtime_entry(data)
    if direct is not None:
        return [direct]

    return _normalize_mapping_payload(data)


def _normalize_mapping_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a name→value mapping into runtime observations."""
    observations: list[dict[str, Any]] = []
    for name, value in data.items():
        if isinstance(value, dict):
            entry = dict(value)
            entry.setdefault("function", name)
            normalized = _normalize_runtime_entry(entry)
        else:
            count = _coerce_non_negative_int(value)
            normalized = (
                _normalize_runtime_entry({"function": name, "count": count})
                if count is not None
                else None
            )
        if normalized is None:
            continue
        observations.append(normalized)
    return observations


def normalize_runtime_payload(data: object) -> list[dict[str, Any]]:
    """Normalize supported runtime payload shapes into ImpactGuard observations."""
    if isinstance(data, list):
        return [
            normalized
            for item in data
            if (normalized := _normalize_runtime_entry(item)) is not None
        ]

    if isinstance(data, dict):
        return _normalize_dict_payload(data)

    return []


def load_runtime_observations(path: str) -> list[dict[str, Any]]:
    """Load and normalize runtime observations from JSON.

    The inbound JSON is validated against the expected schema
    (list of ``{function, count}`` dicts).  When validation fails, errors
    are logged and an empty list is returned so downstream processing
    degrades gracefully.
    """
    from .schema import validate_runtime as _validate_runtime

    with open(path) as f:
        raw = json.load(f)

    valid, errors = _validate_runtime(raw)
    if not valid:
        for err in errors:
            _log.error("Runtime data validation error: %s", err)
        _log.warning(
            "Runtime data from '%s' failed validation — treating as absent.",
            path,
        )
        return []

    return normalize_runtime_payload(raw)


def build_runtime_index(observations: list[dict[str, Any]]) -> dict[str, int]:
    """Build an alias → count index for normalized runtime observations."""
    runtime: dict[str, int] = {}
    for item in observations:
        count = _coerce_non_negative_int(item.get("count")) or 0
        for alias in item.get("aliases", []):
            runtime[alias] = runtime.get(alias, 0) + count
    return runtime


def lookup_runtime_count(runtime: dict[str, int], *names: str) -> int:
    """Return the first matching runtime count for any name alias."""
    for name in names:
        for alias in runtime_name_variants(name):
            if alias in runtime:
                return runtime[alias]
    return 0


def runtime_callsite_entries(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert runtime observations with invocation-shape data into call entries."""
    calls: list[dict[str, Any]] = []
    for item in observations:
        args_count = _coerce_non_negative_int(item.get("args_count"))
        kwargs = _coerce_kwargs(item.get("kwargs"))
        if args_count is None and kwargs is None:
            continue

        fqname = item.get("canonical") or item.get("function", "")
        if not isinstance(fqname, str) or not fqname:
            continue

        calls.append(
            {
                "fqname": fqname,
                "file": "runtime",
                "lineno": 0,
                "args": args_count or 0,
                "kwargs": kwargs or [],
                "has_starargs": False,
                "has_kwargs": False,
            }
        )
    return calls
