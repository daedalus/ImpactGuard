"""Tests for runtime_intelligence module."""

import pytest

from impactguard.runtime_intelligence import (
    _coerce_non_negative_int,
    _normalize_runtime_entry,
    canonical_runtime_name,
    normalize_runtime_payload,
    runtime_callsite_entries,
    runtime_name_variants,
)


def test_coerce_non_negative_int_bool():
    assert _coerce_non_negative_int(True) is None
    assert _coerce_non_negative_int(False) is None


def test_coerce_non_negative_int_negative():
    assert _coerce_non_negative_int(-5) == 0
    assert _coerce_non_negative_int(5) == 5


def test_coerce_non_negative_int_non_number():
    assert _coerce_non_negative_int("foo") is None


def test_canonical_runtime_name_empty():
    assert canonical_runtime_name("") == ""
    assert canonical_runtime_name(".") == ""
    assert canonical_runtime_name("  ") == ""


def test_canonical_runtime_name_url():
    result = canonical_runtime_name("https://example.com/api.call")
    assert "://" in result


def test_canonical_runtime_name_double_dots():
    result = canonical_runtime_name("a..b...c")
    assert ".." not in result


def test_canonical_runtime_name_colon_with_suffix():
    result = canonical_runtime_name("mod.py:func")
    assert "mod" in result
    assert "func" in result


def test_runtime_name_variants_empty():
    assert runtime_name_variants("") == []
    assert runtime_name_variants("  ") == []


def test_normalize_runtime_entry_non_dict():
    assert _normalize_runtime_entry("string") is None
    assert _normalize_runtime_entry(42) is None
    assert _normalize_runtime_entry(None) is None


def test_normalize_runtime_entry_with_language():
    result = _normalize_runtime_entry({"function": "foo", "calls": 5, "language": "rust"})
    assert result is not None
    assert result["language"] == "rust"


def test_normalize_runtime_payload_single_dict():
    result = normalize_runtime_payload({"function": "foo", "hits": 3})
    assert len(result) == 1
    assert result[0]["function"] == "foo"


def test_normalize_runtime_payload_dict_of_values():
    result = normalize_runtime_payload({"foo": {"calls": 5}, "bar": {"calls": 3}})
    assert len(result) == 2


def test_normalize_runtime_payload_primitive():
    assert normalize_runtime_payload(42) == []
    assert normalize_runtime_payload("string") == []


def test_normalize_runtime_payload_dict_with_non_normalizable_value():
    result = normalize_runtime_payload({"foo": "not_a_number"})
    assert result == []


def test_normalize_runtime_payload_dict_item_in_container():
    result = normalize_runtime_payload({"runtime": [{"function": "foo", "calls": 5}]})
    assert len(result) == 1


def test_runtime_callsite_entries_missing_fqname():
    obs = [{"args_count": 3}]
    result = runtime_callsite_entries(obs)
    assert len(result) == 0


def test_runtime_callsite_entries_empty_fqname():
    obs = [{"function": "", "args_count": 1}]
    result = runtime_callsite_entries(obs)
    assert len(result) == 0


def test_runtime_callsite_entries_valid():
    obs = [{"function": "foo", "args_count": 2, "kwargs": ["x"]}]
    result = runtime_callsite_entries(obs)
    assert len(result) == 1
    assert result[0]["fqname"] == "foo"


def test_runtime_callsite_entries_no_shape_data():
    obs = [{"function": "foo", "canonical": "foo"}]
    result = runtime_callsite_entries(obs)
    assert result == []


# ── Runtime data validation on ingest ───────────────────────────────────────


def test_load_runtime_observations_valid(tmp_path):
    """Valid runtime JSON is loaded and normalized successfully."""
    from impactguard.runtime_intelligence import load_runtime_observations

    f = tmp_path / "runtime.json"
    f.write_text('[\n{"function": "mod:foo", "count": 5},\n{"function": "mod:bar", "count": 3}\n]')
    result = load_runtime_observations(str(f))
    assert len(result) == 2
    fqnames = {r["function"] for r in result}
    assert "mod:foo" in fqnames
    assert "mod:bar" in fqnames


def test_load_runtime_observations_invalid_missing_count(tmp_path):
    """Runtime JSON missing required 'count' field returns empty list."""
    from impactguard.runtime_intelligence import load_runtime_observations

    f = tmp_path / "runtime.json"
    f.write_text('[{"function": "mod:foo"}]')
    result = load_runtime_observations(str(f))
    assert result == []


def test_load_runtime_observations_invalid_missing_function(tmp_path):
    """Runtime JSON missing required 'function' field returns empty list."""
    from impactguard.runtime_intelligence import load_runtime_observations

    f = tmp_path / "runtime.json"
    f.write_text('[{"count": 5}]')
    result = load_runtime_observations(str(f))
    assert result == []


def test_load_runtime_observations_not_a_list(tmp_path):
    """Runtime JSON that is not a list returns empty list."""
    from impactguard.runtime_intelligence import load_runtime_observations

    f = tmp_path / "runtime.json"
    f.write_text('"not_a_list"')
    result = load_runtime_observations(str(f))
    assert result == []


def test_load_runtime_observations_empty_list(tmp_path):
    """Empty runtime list is valid and returns empty."""
    from impactguard.runtime_intelligence import load_runtime_observations

    f = tmp_path / "runtime.json"
    f.write_text("[]")
    result = load_runtime_observations(str(f))
    assert result == []
