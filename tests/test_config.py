"""Tests for config.py uncovered validation and helper functions."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── _find_config_file ──────────────────────────────────────────────────────


def test_find_config_file_stops_at_git_boundary(tmp_path):
    from impactguard.config import _find_config_file

    sub = tmp_path / "sub" / "deep"
    sub.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").mkdir()

    found = _find_config_file(start=sub)
    assert found is None


def test_find_config_file_found(tmp_path):
    from impactguard.config import _find_config_file

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("[impactguard]\n")

    found = _find_config_file(start=tmp_path)
    assert found == cfg


def test_find_config_file_not_found(tmp_path):
    from impactguard.config import _find_config_file

    found = _find_config_file(start=tmp_path)
    assert found is None


# ── _resolve_validation_path ──────────────────────────────────────────────


def test_resolve_validation_path_with_path():
    from impactguard.config import _resolve_validation_path

    result = _resolve_validation_path("/some/path.toml")
    assert result == Path("/some/path.toml")


def test_resolve_validation_path_without_path():
    from impactguard.config import _resolve_validation_path

    with patch("impactguard.config._find_config_file") as mock_find:
        mock_find.return_value = None
        result = _resolve_validation_path(None)
        assert result is None


# ── _load_validation_config ───────────────────────────────────────────────


def test_load_validation_config_success(tmp_path):
    from impactguard.config import _load_validation_config

    cfg = tmp_path / "config.toml"
    cfg.write_text("[impactguard]\nverbose = true")

    issues: list[str] = []
    result = _load_validation_config(cfg, issues)
    assert result is not None
    assert result["impactguard"]["verbose"] is True


def test_load_validation_config_toml_error(tmp_path):
    from impactguard.config import _load_validation_config

    cfg = tmp_path / "config.toml"
    cfg.write_text("[[[invalid toml")

    issues: list[str] = []
    result = _load_validation_config(cfg, issues)
    assert result is None
    assert any("TOML parse error" in issue for issue in issues)


# ── _append_top_level_issues ──────────────────────────────────────────────


def test_append_top_level_issues():
    from impactguard.config import _append_top_level_issues

    issues: list[str] = []
    _append_top_level_issues({"impactguard": {}, "other_section": {}}, issues)
    assert len(issues) == 1
    assert "other_section" in issues[0]


def test_append_top_level_issues_impactguard_only():
    from impactguard.config import _append_top_level_issues

    issues: list[str] = []
    _append_top_level_issues({"impactguard": {}}, issues)
    assert len(issues) == 0


# ── _validate_config_value ────────────────────────────────────────────────


def test_validate_config_value_float_range():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("risk", "confidence_threshold", 0.3, 15.0, issues)
    assert len(issues) == 1
    assert "outside the expected range" in issues[0]


def test_validate_config_value_float_ok():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("risk", "confidence_threshold", 0.3, 0.5, issues)
    assert len(issues) == 0


def test_validate_config_value_bool_type_error():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("cli", "verbose", False, "yes", issues)
    assert len(issues) == 1
    assert "boolean" in issues[0]


def test_validate_config_value_bool_ok():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("cli", "verbose", False, True, issues)
    assert len(issues) == 0


def test_validate_config_value_int_type_error():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("tracing", "flush_interval", 10, "ten", issues)
    assert len(issues) == 1
    assert "integer" in issues[0]


def test_validate_config_value_int_not_positive():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("tracing", "flush_interval", 10, 0, issues)
    assert len(issues) == 1
    assert "positive integer" in issues[0]


def test_validate_config_value_int_ok():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("tracing", "flush_interval", 10, 30, issues)
    assert len(issues) == 0


def test_validate_config_value_list_type_error():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("analysis", "suppress", [], "not a list", issues)
    assert len(issues) == 1
    assert "array" in issues[0]


def test_validate_config_value_list_ok():
    from impactguard.config import _validate_config_value

    issues: list[str] = []
    _validate_config_value("analysis", "suppress", [], ["warning"], issues)
    assert len(issues) == 0


# ── _validate_config_section ──────────────────────────────────────────────


def test_validate_config_section_unknown():
    from impactguard.config import _DEFAULTS, _validate_config_section

    known = set(_DEFAULTS["impactguard"].keys())
    issues: list[str] = []
    _validate_config_section("nonexistent", {}, known, issues)
    assert len(issues) == 1
    assert "Unknown section" in issues[0]


def test_validate_config_section_not_dict():
    from impactguard.config import _DEFAULTS, _validate_config_section

    known = set(_DEFAULTS["impactguard"].keys())
    issues: list[str] = []
    _validate_config_section("risk", "not a dict", known, issues)
    assert len(issues) == 1
    assert "must be a TOML table" in issues[0]


def test_validate_config_section_unknown_key():
    from impactguard.config import _DEFAULTS, _validate_config_section

    known = set(_DEFAULTS["impactguard"].keys())
    issues: list[str] = []
    _validate_config_section("risk", {"unknown_key": 0.5}, known, issues)
    assert len(issues) == 1
    assert "Unknown key" in issues[0]


def test_validate_config_section_invalid_value():
    from impactguard.config import _DEFAULTS, _validate_config_section

    known = set(_DEFAULTS["impactguard"].keys())
    issues: list[str] = []
    _validate_config_section("risk", {"confidence_threshold": 50.0}, known, issues)
    assert len(issues) == 1
    assert "outside the expected range" in issues[0]


def test_validate_config_section_ok():
    from impactguard.config import _DEFAULTS, _validate_config_section

    known = set(_DEFAULTS["impactguard"].keys())
    issues: list[str] = []
    _validate_config_section("risk", {"confidence_threshold": 0.5}, known, issues)
    assert len(issues) == 0


# ── validate_config ───────────────────────────────────────────────────────


def test_validate_config_no_file(tmp_path):
    from impactguard.config import validate_config

    with patch("impactguard.config.Path.cwd", return_value=tmp_path):
        issues = validate_config()
    assert len(issues) == 1
    assert "No impactguard.toml found" in issues[0]


def test_validate_config_invalid_toml(tmp_path):
    from impactguard.config import validate_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("[[[bad toml]]]")

    issues = validate_config(str(cfg))
    assert len(issues) == 1
    assert any("TOML parse error" in i for i in issues)


def test_validate_config_impactguard_not_table(tmp_path):
    from impactguard.config import validate_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text('impactguard = "string"')

    issues = validate_config(str(cfg))
    assert len(issues) == 1
    assert "must be a TOML table" in issues[0]


def test_validate_config_top_level_warning(tmp_path):
    from impactguard.config import validate_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("[impactguard]\n[other]\n")

    issues = validate_config(str(cfg))
    assert any("other" in i and "top-level" in i for i in issues)


def test_validate_config_unknown_section(tmp_path):
    from impactguard.config import validate_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("[impactguard]\n[impactguard.mystery]\n")

    issues = validate_config(str(cfg))
    assert any("Unknown section" in i for i in issues)


def test_validate_config_full_valid(tmp_path):
    from impactguard.config import validate_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("""[impactguard]
[impactguard.risk]
confidence_threshold = 0.5
""")

    issues = validate_config(str(cfg))
    assert len(issues) == 0


def test_validate_config_section_unknown_key_in_section(tmp_path):
    from impactguard.config import validate_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("[impactguard]\n[impactguard.risk]\ngarbage_key = 99\n")

    issues = validate_config(str(cfg))
    assert any("Unknown key" in i for i in issues)


# ── reload_config ─────────────────────────────────────────────────────────


def test_reload_config(tmp_path):
    from impactguard.config import reload_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("[impactguard]\n[impactguard.risk]\nconfidence_threshold = 0.9")

    result = reload_config(str(cfg))
    assert result["impactguard"]["risk"]["confidence_threshold"] == 0.9


def test_reload_config_invalid(tmp_path, capsys):
    from impactguard.config import reload_config

    cfg = tmp_path / "impactguard.toml"
    cfg.write_text("not valid toml {{{")

    result = reload_config(str(cfg))
    assert result is not None
