"""Logging utilities for ImpactGuard.

This module sets up the ``"impactguard"`` logger hierarchy.  Following the
Python library best-practice, the root logger ships with a :class:`NullHandler`
so that host applications are fully in control of log output.

Typical usage in a library module::

    from ._logging import get_logger

    _log = get_logger(__name__)

    _log.debug("Extracting %d files", len(files))
    _log.warning("No extractor for %s; skipping", path)

CLI / application usage::

    from impactguard._logging import configure_logging

    configure_logging(level="DEBUG")
"""

import logging
import sys

# The single logger name used across the entire package.
_ROOT_LOGGER_NAME = "impactguard"

# Default format for human-readable output.
_DEFAULT_FORMAT = "%(levelname)s [%(name)s] %(message)s"

# Attach a NullHandler so library users never see "No handler found" warnings.
logging.getLogger(_ROOT_LOGGER_NAME).addHandler(logging.NullHandler())


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``"impactguard"`` hierarchy.

    Args:
        name: Typically ``__name__`` of the calling module.  If the name
            already starts with ``"impactguard"`` it is used as-is; otherwise
            it is prefixed with ``"impactguard."``.

    Returns:
        A :class:`logging.Logger` instance.
    """
    if name.startswith(_ROOT_LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def configure_logging(
    level: str | int = "WARNING",
    fmt: str = _DEFAULT_FORMAT,
    log_file: str | None = None,
    *,
    propagate: bool = True,
) -> logging.Logger:
    """Configure the ``"impactguard"`` logger for application use.

    This function is intended for CLI entry-points and test harnesses.
    Library code should **not** call this; it should only use
    :func:`get_logger` to emit log records.

    Args:
        level: Logging level string (``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
            ``"ERROR"``, ``"CRITICAL"``) or integer constant.
        fmt: :mod:`logging` format string.
        log_file: Optional path to a file where log records are written in
            addition to *stderr*.  The file is opened in append mode.
        propagate: Whether the root ``"impactguard"`` logger should propagate
            to the root Python logger.  Defaults to *True* so that host
            applications can intercept all records if they wish.

    Returns:
        The configured ``"impactguard"`` :class:`logging.Logger`.
    """
    root = logging.getLogger(_ROOT_LOGGER_NAME)

    # Remove handlers that were previously installed by this function so that
    # calling configure_logging() multiple times doesn't multiply handlers.
    for handler in list(root.handlers):
        if getattr(handler, "_impactguard_managed", False):
            root.removeHandler(handler)
            handler.close()

    # Resolve level
    if isinstance(level, str):
        numeric_level = getattr(logging, level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError(f"Invalid log level: {level!r}")
    else:
        numeric_level = level

    root.setLevel(numeric_level)
    root.propagate = propagate

    formatter = logging.Formatter(fmt)

    # Console handler (stderr)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    console._impactguard_managed = True  # type: ignore[attr-defined]
    root.addHandler(console)

    # Optional file handler
    if log_file:
        fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        fh.setLevel(numeric_level)
        fh.setFormatter(formatter)
        fh._impactguard_managed = True  # type: ignore[attr-defined]
        root.addHandler(fh)

    return root


def _level_from_config() -> str:
    """Read the log level from the ImpactGuard config, defaulting to WARNING."""
    try:
        from .config import get as _cfg_get

        return str(_cfg_get("logging", "level", "WARNING"))
    except Exception:
        return "WARNING"


__all__: list[str] = [
    "get_logger",
    "configure_logging",
]
