"""Tests for the adversarial synthetic generator.

Each test verifies that ImpactGuard correctly detects the breaking change
that a particular camouflage strategy attempts to hide.  A test *passes*
when ``compare()`` reports the expected breaking patterns — proving that
the system is not fooled by the disguise.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

import pytest

from impactguard.adversarial_generator import (
    AdversarialPair,
    generate,
    generate_all,
    list_strategies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmpjson(data: Any) -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, f)
    f.close()
    return f.name


def _rm(*paths: str) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


def _run_compare(pair: AdversarialPair) -> dict[str, list[str]]:
    """Serialise the pair to temp files and run ``compare()``."""
    from impactguard.compare_signatures import compare

    old_path = _tmpjson(pair.old_signatures)
    new_path = _tmpjson(pair.new_signatures)
    try:
        return compare(old_path, new_path, include_private=True)
    finally:
        _rm(old_path, new_path)


def _assert_caught(pair: AdversarialPair) -> None:
    """Assert that ImpactGuard flags every expected breaking pattern."""
    result = _run_compare(pair)
    ok, failures = pair.verify(result)
    assert ok, (
        f"Strategy {pair.strategy_name!r} was NOT caught.\n"
        f"Failures: {failures}\n"
        f"Breaking reported: {result['breaking']}\n"
        f"Nonbreaking reported: {result['nonbreaking']}"
    )


def _assert_camouflage_present(pair: AdversarialPair) -> None:
    """Assert that the expected non-breaking noise entries are also present."""
    result = _run_compare(pair)
    for pattern in pair.expected_nonbreaking_patterns:
        assert any(pattern in item for item in result["nonbreaking"]), (
            f"Strategy {pair.strategy_name!r}: expected nonbreaking noise "
            f"{pattern!r} not found in {result['nonbreaking']}"
        )


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_list_strategies_returns_ten(self):
        assert len(list_strategies()) == 10

    def test_all_strategy_names_are_strings(self):
        for name in list_strategies():
            assert isinstance(name, str)

    def test_generate_unknown_strategy_raises(self):
        with pytest.raises(KeyError, match="Unknown strategy"):
            generate("nonexistent_strategy")

    def test_generate_all_returns_list_of_pairs(self):
        pairs = generate_all()
        assert len(pairs) == 10
        for pair in pairs:
            assert isinstance(pair, AdversarialPair)

    def test_generate_all_strategy_names_unique(self):
        names = [p.strategy_name for p in generate_all()]
        assert len(names) == len(set(names))

    def test_every_listed_strategy_is_generatable(self):
        for name in list_strategies():
            pair = generate(name)
            assert pair.strategy_name == name

    def test_every_pair_has_expected_breaking_patterns(self):
        for pair in generate_all():
            assert len(pair.expected_breaking_patterns) >= 1, (
                f"{pair.strategy_name} must declare at least one expected breaking pattern"
            )

    def test_every_pair_has_non_empty_description(self):
        for pair in generate_all():
            assert pair.description.strip()

    def test_every_pair_has_non_empty_camouflage_notes(self):
        for pair in generate_all():
            assert pair.camouflage_notes.strip()

    def test_every_pair_has_old_and_new_signatures(self):
        for pair in generate_all():
            assert pair.old_signatures
            assert pair.new_signatures


# ---------------------------------------------------------------------------
# Seeding / reproducibility tests
# ---------------------------------------------------------------------------


class TestSeeding:
    """Verify that the generator is deterministic when seeded and random-looking."""

    def test_same_seed_produces_identical_pair(self):
        """Identical seeds must produce byte-for-byte identical pairs."""
        for name in list_strategies():
            p1 = generate(name, seed=42)
            p2 = generate(name, seed=42)
            assert p1.old_signatures == p2.old_signatures, name
            assert p1.new_signatures == p2.new_signatures, name
            assert p1.description == p2.description, name
            assert p1.camouflage_notes == p2.camouflage_notes, name
            assert p1.expected_breaking_patterns == p2.expected_breaking_patterns, name

    def test_different_seeds_produce_different_pairs(self):
        """Different seeds must yield at least one differing pair (across all strategies)."""
        differs = False
        for name in list_strategies():
            p1 = generate(name, seed=0)
            p2 = generate(name, seed=999)
            if p1.old_signatures != p2.old_signatures or p1.new_signatures != p2.new_signatures:
                differs = True
                break
        assert differs, (
            "All strategies produced identical pairs for seed=0 and seed=999 — "
            "randomization is not working."
        )

    def test_generate_all_same_seed_is_reproducible(self):
        """generate_all with same seed returns an identical list."""
        pairs_a = generate_all(seed=7)
        pairs_b = generate_all(seed=7)
        assert len(pairs_a) == len(pairs_b)
        for a, b in zip(pairs_a, pairs_b):
            assert a.old_signatures == b.old_signatures
            assert a.new_signatures == b.new_signatures

    def test_generate_all_different_seeds_differ(self):
        """generate_all with different seeds must produce at least one differing entry."""
        pairs_a = generate_all(seed=1)
        pairs_b = generate_all(seed=2)
        differs = any(
            a.old_signatures != b.old_signatures or a.new_signatures != b.new_signatures
            for a, b in zip(pairs_a, pairs_b)
        )
        assert differs, (
            "generate_all produced identical results for seed=1 and seed=2 — "
            "randomization is not working."
        )

    def test_no_seed_returns_valid_pair(self):
        """Unseeded generate() must still return a well-formed pair."""
        for name in list_strategies():
            pair = generate(name)
            assert isinstance(pair, AdversarialPair)
            assert pair.old_signatures
            assert pair.new_signatures

    def test_string_seed_is_accepted(self):
        """Seeds may be strings; same string seed must be reproducible."""
        p1 = generate("type_narrowing_disguised_as_cleanup", seed="hello")
        p2 = generate("type_narrowing_disguised_as_cleanup", seed="hello")
        assert p1.old_signatures == p2.old_signatures
        assert p1.new_signatures == p2.new_signatures

    def test_seeded_fqnames_vary_across_seeds(self):
        """The randomized fqname must differ for at least two distinct seeds."""
        seen_fqnames: set[str] = set()
        strategy = list_strategies()[0]
        for s in range(20):
            pair = generate(strategy, seed=s)
            fqname = pair.old_signatures[0]["fqname"]
            seen_fqnames.add(fqname)
        assert len(seen_fqnames) > 1, (
            "All 20 different seeds produced the same fqname — "
            "names are not being randomized."
        )


# ---------------------------------------------------------------------------
# AdversarialPair.verify() unit tests
# ---------------------------------------------------------------------------


class TestAdversarialPairVerify:
    def _pair(self, patterns: list[str]) -> AdversarialPair:
        return AdversarialPair(
            strategy_name="test",
            description="test",
            camouflage_notes="test",
            old_signatures=[],
            new_signatures=[],
            expected_breaking_patterns=patterns,
        )

    def test_verify_passes_when_all_patterns_present(self):
        pair = self._pair(["REMOVED", "mymodule"])
        result = {"breaking": ["REMOVED: mymodule:foo"], "nonbreaking": []}
        ok, failures = pair.verify(result)
        assert ok
        assert failures == []

    def test_verify_fails_when_pattern_missing(self):
        pair = self._pair(["REMOVED", "REQUIRED"])
        result = {"breaking": ["REMOVED: mymodule:foo"], "nonbreaking": []}
        ok, failures = pair.verify(result)
        assert not ok
        assert any("REQUIRED" in f for f in failures)

    def test_verify_passes_with_empty_patterns(self):
        pair = self._pair([])
        result = {"breaking": [], "nonbreaking": []}
        ok, failures = pair.verify(result)
        assert ok
        assert failures == []

    def test_verify_handles_missing_breaking_key(self):
        pair = self._pair(["REMOVED"])
        result = {"nonbreaking": []}
        ok, failures = pair.verify(result)
        assert not ok


# ---------------------------------------------------------------------------
# Per-strategy detection tests
# ---------------------------------------------------------------------------


class TestStrategyDetection:
    """Verify that ImpactGuard is NOT fooled by any camouflage strategy."""

    def test_required_param_hidden_by_type_annotation(self):
        pair = generate("required_param_hidden_by_type_annotation")
        _assert_caught(pair)

    def test_required_param_camouflage_noise_present(self):
        """Type annotation addition should be visible as a nonbreaking entry."""
        pair = generate("required_param_hidden_by_type_annotation")
        result = _run_compare(pair)
        # The important check: the breaking entry must be present.
        breaking = result["breaking"]
        assert any("REQUIRED_POSITIONAL_ADDED" in b for b in breaking)
        # Camouflage: type annotation on 'a' produces a TYPE_WIDENED nonbreaking entry.
        assert any("TYPE_WIDENED" in nb for nb in result["nonbreaking"]), (
            "Expected TYPE_WIDENED nonbreaking entry from annotation on 'a'"
        )

    def test_positional_reorder_hidden_by_optional_add(self):
        pair = generate("positional_reorder_hidden_by_optional_add")
        _assert_caught(pair)

    def test_positional_reorder_camouflage_noise_present(self):
        pair = generate("positional_reorder_hidden_by_optional_add")
        _assert_camouflage_present(pair)

    def test_type_narrowing_disguised_as_cleanup(self):
        pair = generate("type_narrowing_disguised_as_cleanup")
        _assert_caught(pair)

    def test_type_narrowing_breaking_not_nonbreaking(self):
        """Narrowing must be classified as breaking, not as a type widening."""
        pair = generate("type_narrowing_disguised_as_cleanup")
        result = _run_compare(pair)
        assert not any("TYPE_WIDENED" in nb for nb in result["nonbreaking"]), (
            "Type narrowing must NOT appear as TYPE_WIDENED"
        )

    def test_kwonly_removal_with_optional_addition(self):
        pair = generate("kwonly_removal_with_optional_addition")
        _assert_caught(pair)

    def test_kwonly_removal_camouflage_noise_present(self):
        pair = generate("kwonly_removal_with_optional_addition")
        _assert_camouflage_present(pair)

    def test_vararg_removal_with_kwarg_addition(self):
        pair = generate("vararg_removal_with_kwarg_addition")
        _assert_caught(pair)

    def test_vararg_removal_no_nonbreaking_noise(self):
        """The **kwargs addition is not a tracked non-breaking event here."""
        pair = generate("vararg_removal_with_kwarg_addition")
        result = _run_compare(pair)
        # The critical check: *args removal IS in breaking
        assert any("*args_REMOVED" in b for b in result["breaking"])

    def test_return_type_narrowing_disguised_as_guarantee(self):
        pair = generate("return_type_narrowing_disguised_as_guarantee")
        _assert_caught(pair)

    def test_return_type_narrowing_is_breaking_not_widening(self):
        pair = generate("return_type_narrowing_disguised_as_guarantee")
        result = _run_compare(pair)
        assert not any("RETURN TYPE_WIDENED" in nb for nb in result["nonbreaking"]), (
            "Return type narrowing must NOT appear as RETURN TYPE_WIDENED"
        )

    def test_decorator_removal_hidden_by_optional_kwarg(self):
        pair = generate("decorator_removal_hidden_by_optional_kwarg")
        _assert_caught(pair)

    def test_decorator_removal_camouflage_noise_present(self):
        pair = generate("decorator_removal_hidden_by_optional_kwarg")
        _assert_camouflage_present(pair)

    def test_required_kwonly_added_with_misleading_name(self):
        pair = generate("required_kwonly_added_with_misleading_name")
        _assert_caught(pair)

    def test_required_kwonly_misleading_name_is_still_required(self):
        """The 'optional_context' name must not prevent the REQUIRED detection."""
        pair = generate("required_kwonly_added_with_misleading_name")
        result = _run_compare(pair)
        assert any("REQUIRED_KWONLY_ADDED" in b for b in result["breaking"])

    def test_function_removal_hidden_by_rename_addition(self):
        pair = generate("function_removal_hidden_by_rename_addition")
        _assert_caught(pair)

    def test_function_removal_rename_camouflage_noise_present(self):
        pair = generate("function_removal_hidden_by_rename_addition")
        _assert_camouflage_present(pair)

    def test_kwargs_removal_hidden_by_explicit_params(self):
        pair = generate("kwargs_removal_hidden_by_explicit_params")
        _assert_caught(pair)

    def test_kwargs_removal_camouflage_noise_present(self):
        pair = generate("kwargs_removal_hidden_by_explicit_params")
        _assert_camouflage_present(pair)


# ---------------------------------------------------------------------------
# Bulk detection: every strategy must be caught
# ---------------------------------------------------------------------------


class TestBulkDetection:
    @pytest.mark.parametrize("strategy_name", list_strategies())
    def test_every_strategy_is_caught(self, strategy_name: str):
        """Parametrized: ImpactGuard must catch the breaking change in every strategy."""
        pair = generate(strategy_name)
        _assert_caught(pair)

    @pytest.mark.parametrize("strategy_name", list_strategies())
    def test_every_strategy_produces_non_empty_breaking_list(self, strategy_name: str):
        pair = generate(strategy_name)
        result = _run_compare(pair)
        assert result["breaking"], (
            f"Strategy {strategy_name!r} produced no breaking changes — "
            "the generator is misconfigured."
        )
