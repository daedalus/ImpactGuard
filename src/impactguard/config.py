"""Configuration loader for ImpactGuard.

Reads ``impactguard.toml`` from the current directory or any parent directory.
Falls back to built-in defaults when no config file is found.
All public API reads values through :func:`get`, so the rest of the package
never needs to hard-code thresholds.
"""

import sys
import tomllib
from pathlib import Path
from typing import Any

# ── Built-in defaults ─────────────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "impactguard": {
        "severity_scores": {
            "REMOVED": 1.0,
            "REQUIRED": 0.9,
            "POSITIONAL REORDER": 0.8,
            "KWONLY REMOVED": 0.8,
            "*args REMOVED": 0.7,
            "**kwargs REMOVED": 0.7,
            "OPTIONAL": 0.3,
            "ADDED": 0.1,
            "TYPE CHANGED": 0.6,
            "RETURN TYPE CHANGED": 0.5,
            "DECORATOR REMOVED": 0.6,
            "DECORATOR ADDED": 0.4,
        },
        "risk": {
            "confidence_threshold": 0.3,
            "high_exposure_min": 0.1,
            "medium_exposure_min": 0.01,
            "block_unknown": False,
        },
        "patches": {
            "target_file_match": 1.0,
            "target_lineno_match": 1.0,
            "target_name_only": 0.5,
            "target_default": 0.2,
            "structural_default": 1.0,
            "structural_optional": 1.0,
            "structural_kwarg": 0.8,
            "structural_positional": 0.3,
            "semantic_required": 0.6,
            "semantic_default": 1.0,
            "complexity_multiline": 0.7,
            "complexity_decorators": 0.5,
            "complexity_annotations": 0.5,
            "complexity_nested": 0.5,
        },
        "tracing": {
            "sample_rate": 0.01,
            "flush_interval": 10,
        },
        "output": {
            "report_title": "API Risk Report",
            "default_html_output": "api_report.html",
            "default_json_output": "report.json",
            "default_runtime_output": ".runtime_calls.json",
        },
        "cli": {
            "verbose": False,
            "auto_open": False,
        },
        "analysis": {
            "include_private": False,
            "transitive_depth": 0,
            "suppress": [],
        },
    }
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict that is *override* deep-merged on top of *base*."""
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _find_config_file(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: cwd) looking for ``impactguard.toml``."""
    search = start or Path.cwd()
    for directory in [search, *search.parents]:
        candidate = directory / "impactguard.toml"
        if candidate.is_file():
            return candidate
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load ImpactGuard configuration, merging with built-in defaults.

    Args:
        config_path: Explicit path to a TOML config file.  If *None* the
            function searches for ``impactguard.toml`` starting at the current
            working directory and walking up to the filesystem root.

    Returns:
        Merged configuration dictionary with all defaults applied.
    """
    if config_path:
        path: Path | None = Path(config_path)
    else:
        path = _find_config_file()

    if path is None or not path.is_file():
        return _DEFAULTS

    try:
        with open(path, "rb") as f:
            raw: dict[str, Any] = tomllib.load(f)
    except Exception as exc:
        print(
            f"Warning: impactguard: could not parse config file '{path}': {exc}; "
            "using built-in defaults.",
            file=sys.stderr,
        )
        return _DEFAULTS

    return _deep_merge(_DEFAULTS, raw)


# Module-level singleton — loaded lazily, shared across the package.
_config: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """Return the current configuration, loading it on first access."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config(config_path: str | None = None) -> dict[str, Any]:
    """Force re-load configuration from disk.

    Args:
        config_path: Explicit path to config file.

    Returns:
        Freshly loaded configuration dictionary.
    """
    global _config
    _config = load_config(config_path)
    return _config


def get(section: str, key: str, default: Any = None) -> Any:
    """Convenience accessor for ``config["impactguard"][section][key]``.

    Args:
        section: Sub-section name under ``[impactguard]``.
        key: Key within the sub-section.
        default: Value returned when the key is absent.

    Returns:
        Configuration value or *default*.
    """
    cfg = get_config()
    return cfg.get("impactguard", {}).get(section, {}).get(key, default)
