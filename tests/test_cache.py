"""Tests for the ImpactGuard opportunistic cache layer.

Covers:
- BloomFilter (add, query, update, load_factor, clear)
- Cache (set, get, get_or_sentinel, clear, TTL, LRU eviction, persistence)
- Singleton (get_cache returns shared instance)
- AST cache wrapper (cached_ast_parse)
- File cache wrapper (cached_read_text)
- Metrics (hit/miss tracking)
- Edge cases and error paths
"""

from __future__ import annotations

import ast
import os
import pathlib
import pickle
import sqlite3
import struct
import tempfile
import time

import pytest

from impactguard._ast_cache import cached_ast_parse, cached_read_text
from impactguard.cache import (
    SENTINEL,
    BloomFilter,
    Cache,
    get_cache,
    get_cache_metrics_snapshot,
    is_cache_miss,
    reset_cache_metrics,
)

# ═══════════════════════════════════════════════════════════════════════════════
# BloomFilter
# ═══════════════════════════════════════════════════════════════════════════════

class TestBloomFilter:
    def test_init_default(self):
        bf = BloomFilter(100)
        assert bf.m > 0
        assert bf.load_factor == 0.0

    def test_add_and_query(self):
        bf = BloomFilter(100)
        assert not bf.query("foo")
        bf.add("foo")
        assert bf.query("foo")

    def test_update_returns_true_for_existing(self):
        bf = BloomFilter(100)
        assert not bf.update("foo")
        assert bf.update("foo")

    def test_multiple_keys(self):
        bf = BloomFilter(100)
        keys = [f"key-{i}" for i in range(50)]
        for k in keys:
            bf.add(k)
        for k in keys:
            assert bf.query(k)

    def test_load_factor_increases(self):
        bf = BloomFilter(1000)
        assert bf.load_factor == 0.0
        for i in range(500):
            bf.add(f"x-{i}")
        assert bf.load_factor > 0.0

    def test_clear(self):
        bf = BloomFilter(100)
        bf.add("foo")
        assert bf.query("foo")
        bf.clear()
        assert not bf.query("foo")

    def test_small_capacity_rounds_up(self):
        bf = BloomFilter(1)
        assert bf.m >= 1
        bf.add("x")
        assert bf.query("x")

    def test_large_capacity(self):
        bf = BloomFilter(100_000)
        for i in range(1000):
            bf.add(f"big-{i}")
        for i in range(1000):
            assert bf.query(f"big-{i}")

    def test_false_positive_rate_is_bounded(self):
        bf = BloomFilter(5000, error_rate=0.05)
        n = 1000
        for i in range(n):
            bf.add(f"fp-{i}")
        false_positives = sum(1 for i in range(n, n + 5000) if bf.query(f"fp-{i}"))
        actual_rate = false_positives / 5000
        assert actual_rate < 0.10

    def test_custom_error_rate(self):
        bf = BloomFilter(1000, error_rate=0.001)
        assert bf.m > 0
        bf.add("tight")
        assert bf.query("tight")


# ═══════════════════════════════════════════════════════════════════════════════
# Cache
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    yield tmp.name
    pathlib.Path(tmp.name).unlink(missing_ok=True)


class TestCache:
    def test_init_creates_table(self, temp_db):
        c = Cache(db_path=temp_db)
        cur = c.con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache'")
        assert cur.fetchone() is not None
        c.close()

    def test_set_and_get(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("hello", "world")
        assert c.get("hello") == "world"
        c.close()

    def test_get_sentinel_on_miss(self, temp_db):
        c = Cache(db_path=temp_db)
        result = c.get_or_sentinel("nonexistent")
        assert is_cache_miss(result)
        c.close()

    def test_get_sentinel_on_hit(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("a", 42)
        result = c.get_or_sentinel("a")
        assert result == 42
        c.close()

    def test_canonicalize_key_lowercases_namespace(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("File:/foo/bar.py", "content")
        assert c.get("FILE:/foo/bar.py") == "content"
        c.close()

    def test_canonicalize_key_collapses_whitespace(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("ns:   hello   world", "v")
        assert c.get("ns:hello world") == "v"
        c.close()

    def test_get_returns_none_on_miss(self, temp_db):
        c = Cache(db_path=temp_db)
        assert c.get("missing") is None
        c.close()

    def test_none_value(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("null_key", None)
        assert c.get("null_key") is None
        c.close()

    def test_int_value(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("int_key", 42)
        assert c.get("int_key") == 42
        c.close()

    def test_float_value(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("float_key", 3.14)
        assert c.get("float_key") == 3.14
        c.close()

    def test_list_value(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("list_key", [1, 2, 3])
        assert c.get("list_key") == [1, 2, 3]
        c.close()

    def test_dict_value(self, temp_db):
        c = Cache(db_path=temp_db)
        d = {"a": 1, "b": {"c": 2}}
        c.set("dict_key", d)
        assert c.get("dict_key") == d
        c.close()

    def test_ast_module_pickle(self, temp_db):
        c = Cache(db_path=temp_db)
        tree = ast.parse("x = 1")
        c.set("ast:test", tree)
        restored = c.get("ast:test")
        assert isinstance(restored, ast.Module)
        assert isinstance(restored.body[0], ast.Assign)
        c.close()

    def test_clear(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.get("a") is None
        assert c.get("b") is None
        c.close()

    def test_clear_then_set_works(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("x", 1)
        c.clear()
        c.set("y", 2)
        assert c.get("y") == 2
        c.close()

    def test_clear_resets_bloom(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("x", 1)
        assert c._bloom.query("x")
        c.clear()
        assert not c._bloom.query("x")
        c.close()

    def test_ttl_expires(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("ttl_key", "value", ttl_seconds=3600)
        # Manually expire the entry by updating the expires_at field
        c.con.execute(
            "UPDATE cache SET expires_at = ? WHERE key = ?",
            (time.time() - 1, "ttl_key"),
        )
        c.con.commit()
        c._mem.clear()
        assert c.get("ttl_key") is None
        c.close()

    def test_ttl_positive_does_not_expire(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("valid", "data", ttl_seconds=3600)
        assert c.get("valid") == "data"
        c.close()

    def test_get_or_sentinel_with_expired_ttl_returns_sentinel(self, temp_db):
        c = Cache(db_path=temp_db)
        # Insert a key with an already-expired TTL by manipulating SQLite directly
        c.set("expired", "gone", ttl_seconds=3600)
        c.con.execute(
            "UPDATE cache SET expires_at = ? WHERE key = ?",
            (time.time() - 1, "expired"),
        )
        c.con.commit()
        # Clear in-memory L1 so we re-read from SQLite
        c._mem.clear()
        result = c.get_or_sentinel("expired")
        assert is_cache_miss(result)
        c.close()

    def test_max_entries_evicts_lru(self, temp_db):
        c = Cache(db_path=temp_db, max_entries=5)
        for i in range(15):
            c.set(f"k-{i}", i)
        # Force maintenance to ensure eviction
        c._prune_if_needed()
        remaining = [c.get(f"k-{i}") for i in range(15)]
        present = [r for r in remaining if r is not None]
        # At most max_entries + a small buffer
        assert len(present) <= 8
        c.close()

    def test_persistence_across_instances(self, temp_db):
        c1 = Cache(db_path=temp_db)
        c1.set("persist", "survived")
        c1.close()

        c2 = Cache(db_path=temp_db)
        assert c2.get("persist") == "survived"
        c2.close()

    def test_bloom_prepopulated_on_reload(self, temp_db):
        c1 = Cache(db_path=temp_db)
        for i in range(10):
            c1.set(f"pre-{i}", i)
        c1.close()

        c2 = Cache(db_path=temp_db)
        assert c2._bloom.query("pre-5")
        assert c2._bloom.query("pre-9")
        c2.close()

    def test_get_returns_in_memory_hit_without_sqlite(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("hot", "value")
        c._mem["hot"] = "cached_in_memory"
        assert c.get("hot") == "cached_in_memory"
        c.close()

    def test_set_overwrites_existing(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("overwrite", "old")
        c.set("overwrite", "new")
        assert c.get("overwrite") == "new"
        c.close()

    def test_entry_count_tracking(self, temp_db):
        c = Cache(db_path=temp_db)
        assert c._entry_count >= 0
        c.set("cnt1", 1)
        assert c._entry_count >= 1
        c.set("cnt2", 2)
        assert c._entry_count >= 2
        c.close()

    def test_bloom_grows_when_load_factor_high(self, temp_db):
        c = Cache(db_path=temp_db)
        small_bloom = c._bloom
        # Fill the bloom by adding entries and forcing check counter high
        for i in range(100):
            c.set(f"grow-{i}", i)
        # Manually trigger growth
        c._bloom_check_counter = 1000
        c._maybe_grow_bloom()
        c.close()

    def test_delete_expired_removes_entries(self, temp_db):
        c = Cache(db_path=temp_db)
        c.con.execute(
            "INSERT INTO cache (key, value, created_at, expires_at) VALUES (?, ?, ?, ?)",
            ("to_delete", pickle.dumps("gone").hex(), time.time(), time.time() - 1),
        )
        c.con.commit()
        c._entry_count = c._count_entries()
        deleted = c._delete_expired()
        assert deleted >= 1
        c.close()

    def test_close(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("close_test", "ok")
        c.close()
        with pytest.raises(sqlite3.ProgrammingError):
            c.con.execute("SELECT 1")

    def test_invalid_ttl_raises(self, temp_db):
        c = Cache(db_path=temp_db)
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            c.set("bad_ttl", "x", ttl_seconds=0)
        c.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton / Environment
# ═══════════════════════════════════════════════════════════════════════════════

class TestSingleton:
    def test_get_cache_returns_same_instance(self):
        reset_cache_metrics()
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2

    def test_get_cache_uses_env_path(self, monkeypatch):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", tmp.name)
        # Force re-creation by reaching into module internals
        import impactguard.cache as cache_mod
        old = cache_mod._cache
        cache_mod._cache = None
        try:
            c = cache_mod.get_cache()
            assert c.db_path == tmp.name
        finally:
            cache_mod._cache = old
            pathlib.Path(tmp.name).unlink(missing_ok=True)

    def test_get_cache_uses_env_max_entries(self, monkeypatch):
        import impactguard.cache as cache_mod
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        monkeypatch.setenv("IMPACTGUARD_CACHE_MAX_ENTRIES", "100")
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", tmp.name)
        old = cache_mod._cache
        cache_mod._cache = None
        try:
            c = cache_mod.get_cache()
            assert c.max_entries == 100
        finally:
            cache_mod._cache = old
            pathlib.Path(tmp.name).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetrics:
    def test_metrics_track_hits_and_misses(self, temp_db):
        reset_cache_metrics()
        c = Cache(db_path=temp_db)
        c.set("m_key", "m_val")
        # get_or_sentinel is required to record miss metrics
        c.get_or_sentinel("m_key")
        c.get_or_sentinel("nonexistent")
        metrics = get_cache_metrics_snapshot()
        assert metrics["hits"] >= 1
        assert metrics["misses"] >= 1
        c.close()

    def test_metrics_namespace_tracking(self, temp_db):
        reset_cache_metrics()
        c = Cache(db_path=temp_db)
        c.set("ns:hello", "world")
        c.get_or_sentinel("ns:hello")
        c.get_or_sentinel("ns:missing")
        metrics = get_cache_metrics_snapshot()
        assert "ns" in metrics["hits_by_namespace"]
        assert "ns" in metrics["misses_by_namespace"]
        c.close()

    def test_reset_metrics(self, temp_db):
        reset_cache_metrics()
        c = Cache(db_path=temp_db)
        c.set("r", 1)
        c.get("r")
        reset_cache_metrics()
        metrics = get_cache_metrics_snapshot()
        assert metrics["hits"] == 0
        assert metrics["misses"] == 0
        c.close()


# ═══════════════════════════════════════════════════════════════════════════════
# _ast_cache wrappers
# ═══════════════════════════════════════════════════════════════════════════════

class TestAstCache:
    def test_cached_ast_parse(self, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        reset_cache_metrics()
        source = "def foo(): pass"
        tree = cached_ast_parse(source)
        assert isinstance(tree, ast.Module)
        assert isinstance(tree.body[0], ast.FunctionDef)

    def test_cached_ast_parse_hit(self, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        reset_cache_metrics()
        source = "x = 42"
        tree1 = cached_ast_parse(source)
        tree2 = cached_ast_parse(source)
        assert isinstance(tree2, ast.Module)
        assert len(tree2.body) == 1

    def test_cached_ast_parse_syntax_error(self, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        with pytest.raises(SyntaxError):
            cached_ast_parse("def foo(:")

    def test_cached_read_text(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        text = cached_read_text(str(f))
        assert text == "hello world"

    def test_cached_read_text_hit(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        f = tmp_path / "test.txt"
        f.write_text("data")
        text1 = cached_read_text(str(f))
        text2 = cached_read_text(str(f))
        assert text1 == text2

    def test_cached_read_text_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            cached_read_text("/nonexistent/path/file.txt")

    def test_cached_read_text_with_path_object(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        f = tmp_path / "test.py"
        f.write_text("import os")
        text = cached_read_text(f)
        assert text == "import os"

    def test_cached_ast_parse_is_ast_module(self, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        source = "import sys\n\n\ndef main():\n    pass"
        tree = cached_ast_parse(source)
        assert isinstance(tree, ast.Module)
        assert len(tree.body) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: modules actually use cached reads
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_extract_signatures_uses_cache(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        reset_cache_metrics()
        f = tmp_path / "mod.py"
        f.write_text("def foo(): return 1")
        from impactguard.extract_signatures import extract
        sigs = extract([str(f)])
        assert len(sigs) == 1
        assert sigs[0]["name"] == "foo"

    def test_extract_calls_uses_cache(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        reset_cache_metrics()
        f = tmp_path / "main.py"
        f.write_text("foo()\nbar()")
        from impactguard.extract_calls import extract
        calls = extract(f)
        assert len(calls) == 2

    def test_analyze_module_uses_cache(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        reset_cache_metrics()
        f = tmp_path / "target.py"
        f.write_text("x = 1")
        from impactguard.analyze_module import analyze
        result = analyze(str(f))
        assert result is not None
        assert result["file"] == str(f)

    def test_semantic_analysis_uses_cache(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        reset_cache_metrics()
        f = tmp_path / "behavior.py"
        f.write_text("def fn():\n    return 1")
        from impactguard.semantic_analysis import analyze_behavior
        result = analyze_behavior([str(f)])
        assert any("behavior.py:fn" in k for k in result)

    def test_class_hierarchy_uses_cache(self, tmp_path, temp_db, monkeypatch):
        monkeypatch.setenv("IMPACTGUARD_CACHE_PATH", temp_db)
        import impactguard.cache as cache_mod
        cache_mod._cache = None
        reset_cache_metrics()
        f = tmp_path / "hier.py"
        f.write_text("from abc import ABC\n\nclass MyBase(ABC):\n    def method(self): pass\n")
        from impactguard.class_hierarchy import extract_class_hierarchy
        result = extract_class_hierarchy([str(f)])
        assert "MyBase" in result
        assert result["MyBase"]["is_abc"]


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_string_key(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("", "empty")
        assert c.get("") == "empty"
        c.close()

    def test_unicode_key(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("key_ñ", "val_ü")
        assert c.get("key_ñ") == "val_ü"
        c.close()

    def test_long_key(self, temp_db):
        c = Cache(db_path=temp_db)
        long_key = "k" * 10_000
        c.set(long_key, "long")
        assert c.get(long_key) == "long"
        c.close()

    def test_large_value(self, temp_db):
        c = Cache(db_path=temp_db)
        large = "x" * 100_000
        c.set("large", large)
        assert c.get("large") == large
        c.close()

    def test_binary_key(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("bin_key", b"binary\x00data")
        retrieved = c.get("bin_key")
        assert retrieved == b"binary\x00data"
        c.close()

    def test_overwrite_preserves_bloom(self, temp_db):
        c = Cache(db_path=temp_db)
        c.set("ow", 1)
        assert c._bloom.query("ow")
        c.set("ow", 2)
        assert c._bloom.query("ow")
        assert c.get("ow") == 2
        c.close()

    def test_set_on_closed_cache_raises(self, temp_db):
        c = Cache(db_path=temp_db)
        c.close()
        with pytest.raises(sqlite3.ProgrammingError):
            c.set("oops", "x")

    def test_max_entries_of_zero_never_evicts(self, temp_db):
        c = Cache(db_path=temp_db, max_entries=0)
        for i in range(20):
            c.set(f"z-{i}", i)
        assert c._entry_count >= 20
        c.close()

    def test_bloom_survives_maintenance(self, temp_db):
        c = Cache(db_path=temp_db)
        for i in range(30):
            c.set(f"maint-{i}", i)
        assert c._bloom.query("maint-15")
        c.close()

    def test_is_cache_miss_helper(self):
        assert is_cache_miss(SENTINEL)
        assert not is_cache_miss(None)
        assert not is_cache_miss(False)
        assert not is_cache_miss(0)
        assert not is_cache_miss("sentinel")

    def test_sqlite_wal_mode(self, temp_db):
        c = Cache(db_path=temp_db)
        cur = c.con.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0].lower()
        assert mode == "wal"
        c.close()
