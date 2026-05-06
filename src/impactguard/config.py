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
        "languages": {
            # Canonical language names to enable.  "python" is always available.
            # "typescript" requires tree-sitter-typescript (pip install impactguard[languages]).
            "enabled": ["python", "typescript"],
            # Extension-to-language overrides.  Useful when non-standard extensions
            # (e.g. ".mts") should be treated as a known language.
            # Example: {"extension_overrides": {".mts": "typescript"}}
            "extension_overrides": {},
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


def validate_config(config_path: str | None = None) -> list[str]:
    """Validate an ``impactguard.toml`` configuration file.

    Checks that:

    * The file can be parsed as valid TOML.
    * All top-level sections under ``[impactguard]`` are recognised.
    * All keys within each section are recognised.
    * Numeric values fall within sensible bounds (0.0–1.0 for weights and
      fractions; positive integers for ``flush_interval``).

    Args:
        config_path: Explicit path to a TOML config file.  When *None*, the
            function searches for ``impactguard.toml`` from the current
            working directory upward, just like :func:`load_config`.

    Returns:
        A list of human-readable warning/error strings.  An empty list means
        the configuration is valid.  The caller decides whether to treat the
        return value as warnings or fatal errors.
    """
    issues: list[str] = []

    # Locate the file
    if config_path:
        path: Path | None = Path(config_path)
    else:
        path = _find_config_file()

    if path is None or not path.is_file():
        issues.append("No impactguard.toml found; all defaults will be used.")
        return issues

    # Parse TOML
    try:
        with open(path, "rb") as f:
            raw: dict[str, Any] = tomllib.load(f)
    except Exception as exc:
        issues.append(f"TOML parse error in '{path}': {exc}")
        return issues

    # Warn about extra top-level keys (not fatal — other tools may share the file)
    for top_key in raw:
        if top_key != "impactguard":
            issues.append(
                f"INFO: top-level key '{top_key}' is not used by ImpactGuard "
                "(only 'impactguard' is read)."
            )

    ig_raw = raw.get("impactguard", {})
    if not isinstance(ig_raw, dict):
        issues.append("ERROR: '[impactguard]' must be a TOML table.")
        return issues

    _KNOWN_SECTIONS = set(_DEFAULTS["impactguard"].keys())
    for section_name in ig_raw:
        if section_name not in _KNOWN_SECTIONS:
            issues.append(
                f"WARN: Unknown section '[impactguard.{section_name}]' — "
                f"known sections are: {', '.join(sorted(_KNOWN_SECTIONS))}."
            )
            continue

        default_section = _DEFAULTS["impactguard"][section_name]
        user_section = ig_raw[section_name]

        if not isinstance(user_section, dict):
            issues.append(
                f"ERROR: '[impactguard.{section_name}]' must be a TOML table."
            )
            continue

        known_keys = set(default_section.keys()) if isinstance(default_section, dict) else set()
        for key_name, value in user_section.items():
            if known_keys and key_name not in known_keys:
                issues.append(
                    f"WARN: Unknown key '[impactguard.{section_name}].{key_name}' — "
                    f"known keys are: {', '.join(sorted(known_keys))}."
                )
                continue

            # Type / range checks
            default_val = default_section.get(key_name) if isinstance(default_section, dict) else None
            if isinstance(default_val, float) and isinstance(value, (int, float)):
                if not (0.0 <= float(value) <= 10.0):
                    issues.append(
                        f"ERROR: [impactguard.{section_name}].{key_name} = {value!r} "
                        "is outside the expected range [0.0, 10.0]."
                    )
            elif isinstance(default_val, bool) and not isinstance(value, bool):
                issues.append(
                    f"ERROR: [impactguard.{section_name}].{key_name} should be a "
                    f"boolean (true/false), got {type(value).__name__!r}."
                )
            elif isinstance(default_val, int) and not isinstance(default_val, bool):
                if not isinstance(value, int) or isinstance(value, bool):
                    issues.append(
                        f"ERROR: [impactguard.{section_name}].{key_name} should be "
                        f"an integer, got {type(value).__name__!r}."
                    )
                elif value <= 0:
                    issues.append(
                        f"ERROR: [impactguard.{section_name}].{key_name} = {value!r} "
                        "must be a positive integer."
                    )
            elif isinstance(default_val, list) and not isinstance(value, list):
                issues.append(
                    f"ERROR: [impactguard.{section_name}].{key_name} should be a "
                    f"TOML array, got {type(value).__name__!r}."
                )

    return issues
