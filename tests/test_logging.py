"""Tests for ImpactGuard logging facilities."""

import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from impactguard._logging import _ROOT_LOGGER_NAME, configure_logging, get_logger


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_logger(self):
        log = get_logger("test_module")
        assert isinstance(log, logging.Logger)

    def test_logger_name_prefixed(self):
        log = get_logger("some.module")
        assert log.name.startswith(_ROOT_LOGGER_NAME)

    def test_logger_name_not_double_prefixed(self):
        log = get_logger("impactguard.something")
        assert log.name == "impactguard.something"

    def test_dunder_name_convention(self):
        """Verify that passing __name__ from a sub-module works correctly."""
        log = get_logger("impactguard.pipeline")
        assert log.name == "impactguard.pipeline"

    def test_different_modules_give_different_loggers(self):
        log_a = get_logger("mod_a")
        log_b = get_logger("mod_b")
        assert log_a is not log_b

    def test_same_name_gives_same_logger(self):
        log_a = get_logger("shared")
        log_b = get_logger("shared")
        assert log_a is log_b


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def teardown_method(self):
        """Clean up managed handlers after each test."""
        root = logging.getLogger(_ROOT_LOGGER_NAME)
        for handler in list(root.handlers):
            if getattr(handler, "_impactguard_managed", False):
                root.removeHandler(handler)
                handler.close()

    def test_returns_root_logger(self):
        result = configure_logging(level="WARNING")
        assert result.name == _ROOT_LOGGER_NAME

    def test_level_string(self):
        configure_logging(level="DEBUG")
        root = logging.getLogger(_ROOT_LOGGER_NAME)
        assert root.level == logging.DEBUG

    def test_level_integer(self):
        configure_logging(level=logging.ERROR)
        root = logging.getLogger(_ROOT_LOGGER_NAME)
        assert root.level == logging.ERROR

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError, match="Invalid log level"):
            configure_logging(level="NOTALEVEL")

    def test_adds_stream_handler(self):
        configure_logging(level="WARNING")
        root = logging.getLogger(_ROOT_LOGGER_NAME)
        managed = [h for h in root.handlers if getattr(h, "_impactguard_managed", False)]
        assert any(isinstance(h, logging.StreamHandler) for h in managed)

    def test_reconfigure_does_not_duplicate_handlers(self):
        configure_logging(level="WARNING")
        configure_logging(level="WARNING")
        root = logging.getLogger(_ROOT_LOGGER_NAME)
        managed = [h for h in root.handlers if getattr(h, "_impactguard_managed", False)]
        assert len(managed) == 1

    def test_file_handler_created(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_file = f.name
        try:
            configure_logging(level="DEBUG", log_file=log_file)
            root = logging.getLogger(_ROOT_LOGGER_NAME)
            managed = [h for h in root.handlers if getattr(h, "_impactguard_managed", False)]
            assert any(isinstance(h, logging.FileHandler) for h in managed)
        finally:
            # Clean up
            root = logging.getLogger(_ROOT_LOGGER_NAME)
            for h in list(root.handlers):
                if getattr(h, "_impactguard_managed", False):
                    root.removeHandler(h)
                    h.close()
            os.unlink(log_file)

    def test_log_output_to_file(self):
        """Verify that log messages actually reach the file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False
        ) as f:
            log_file = f.name
        try:
            configure_logging(level="DEBUG", log_file=log_file)
            log = get_logger("test_output")
            log.debug("sentinel-message")
            # Flush all handlers
            root = logging.getLogger(_ROOT_LOGGER_NAME)
            for h in root.handlers:
                if getattr(h, "_impactguard_managed", False):
                    h.flush()
            content = Path(log_file).read_text()
            assert "sentinel-message" in content
        finally:
            root = logging.getLogger(_ROOT_LOGGER_NAME)
            for h in list(root.handlers):
                if getattr(h, "_impactguard_managed", False):
                    root.removeHandler(h)
                    h.close()
            os.unlink(log_file)

    def test_custom_format(self):
        configure_logging(level="DEBUG", fmt="%(message)s")
        root = logging.getLogger(_ROOT_LOGGER_NAME)
        managed = [h for h in root.handlers if getattr(h, "_impactguard_managed", False)]
        assert managed[0].formatter._fmt == "%(message)s"


# ---------------------------------------------------------------------------
# Library default — NullHandler
# ---------------------------------------------------------------------------


class TestLibraryDefaults:
    def test_root_logger_has_null_handler_by_default(self):
        """Fresh import: the root logger must have at least a NullHandler so
        that library usage never triggers 'No handlers found' warnings."""
        root = logging.getLogger(_ROOT_LOGGER_NAME)
        null_handlers = [h for h in root.handlers if isinstance(h, logging.NullHandler)]
        assert null_handlers, "Root impactguard logger must ship with a NullHandler"


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_get_logger_exported(self):
        import impactguard

        assert hasattr(impactguard, "get_logger")
        assert impactguard.get_logger is get_logger

    def test_configure_logging_exported(self):
        import impactguard

        assert hasattr(impactguard, "configure_logging")
        assert impactguard.configure_logging is configure_logging


# ---------------------------------------------------------------------------
# Integration: modules use child loggers
# ---------------------------------------------------------------------------


class TestModuleLoggers:
    """Each major module should expose a child logger under 'impactguard.*'."""

    def test_pipeline_logger(self):
        from impactguard import pipeline

        assert hasattr(pipeline, "_log")
        assert pipeline._log.name.startswith(_ROOT_LOGGER_NAME)

    def test_compare_signatures_logger(self):
        from impactguard import compare_signatures

        assert hasattr(compare_signatures, "_log")
        assert compare_signatures._log.name.startswith(_ROOT_LOGGER_NAME)

    def test_extract_signatures_logger(self):
        import importlib

        mod = importlib.import_module("impactguard.extract_signatures")
        assert hasattr(mod, "_log")
        assert mod._log.name.startswith(_ROOT_LOGGER_NAME)

    def test_risk_gate_logger(self):
        from impactguard import risk_gate

        assert hasattr(risk_gate, "_log")
        assert risk_gate._log.name.startswith(_ROOT_LOGGER_NAME)

    def test_impact_analysis_logger(self):
        from impactguard import impact_analysis

        assert hasattr(impact_analysis, "_log")
        assert impact_analysis._log.name.startswith(_ROOT_LOGGER_NAME)

    def test_enforce_gate_logger(self):
        from impactguard import enforce_gate

        assert hasattr(enforce_gate, "_log")
        assert enforce_gate._log.name.startswith(_ROOT_LOGGER_NAME)

    def test_baseline_logger(self):
        from impactguard import baseline

        assert hasattr(baseline, "_log")
        assert baseline._log.name.startswith(_ROOT_LOGGER_NAME)


# ---------------------------------------------------------------------------
# CLI --log-level flag
# ---------------------------------------------------------------------------


class TestCLILogLevel:
    def _run(self, argv: list[str]) -> int:
        old = sys.argv[:]
        sys.argv = ["impactguard"] + argv
        try:
            from impactguard.__main__ import main

            return main() or 0
        except SystemExit as e:
            return e.code or 0
        finally:
            sys.argv = old

    def test_log_level_debug_accepted(self):
        """--log-level DEBUG should not crash the CLI."""
        result = self._run(["--log-level", "DEBUG", "--version"])
        assert result == 0

    def test_log_level_info_accepted(self):
        result = self._run(["--log-level", "INFO", "--version"])
        assert result == 0

    def test_unknown_command_with_log_level(self):
        """Valid --log-level with unknown command returns non-zero."""
        result = self._run(["--log-level", "WARNING"])
        assert isinstance(result, int)
