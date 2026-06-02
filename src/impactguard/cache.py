"""Opportunistic cache for ImpactGuard: Bloom filter + SQLite persistent cache.

Architecture (matching watson_lite pattern)
-------------------------------------------
L1: In-memory ``dict`` — hot path for repeated gets within a session.
L2: Bloom filter — fast negative check avoids SQLite for absent keys.
L3: SQLite — persistent storage with WAL mode, optional TTL, LRU eviction.

Default database path: ``~/.cache/impactguard/cache.db``
Override via environment variable ``IMPACTGUARD_CACHE_PATH``.

Key scheme
----------
Callers provide a namespaced string key (e.g. ``ast:<sha256>``, ``file:<path>``,
``z3:pred:<sha256>``).  The cache canonicalises by lowercasing the namespace
prefix and collapsing whitespace in the suffix (same as watson_lite).

Serialisation
-------------
Values are stored wrapped as ``{"_t": "json", "v": <value>}`` or
``{"_t": "pickle", "v": <base64>}`` so the deserialisation path is unambiguous.
JSON is used for plain dicts/lists/scalars; pickle for ``ast.Module`` and other
complex objects that are not JSON-serialisable.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import json
import logging
import math
import os
import pathlib
import pickle
import sqlite3
import time
from copy import deepcopy
from threading import Lock
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = pathlib.Path.home() / ".cache" / "impactguard"
_DEFAULT_DB_NAME = "cache.db"
_DEFAULT_MAX_ENTRIES = 5000
_MAINTENANCE_INTERVAL_WRITES = 25
_BLOOM_ERROR_RATE = 0.01

SENTINEL = object()
_SENTINEL = SENTINEL


class BloomFilter:
    """Bloom filter backed by a :class:`bytearray`.

    Uses a single SHA-256 hash with bit-variable slicing to produce *k*
    independent index positions from the 256-bit digest.  The filter size *m*
    is rounded up to a power of two so that fast bitwise masking (``& (m-1)``)
    can replace modulo.

    Each position *p* is mapped to a byte in the backing array and a bit
    within that byte::

        byte_idx = (p & mask) // 8   # same as: p >> 3
        bit_idx  = (p & mask) % 8    # same as: p & 7
    """

    def __init__(self, capacity: int, error_rate: float = _BLOOM_ERROR_RATE) -> None:
        n = max(capacity, 1)
        m_ideal = -n * math.log(error_rate) / (math.log(2) ** 2)
        self.m = 1 << max(1, int(m_ideal).bit_length())
        self._mask = self.m - 1
        self._bits_per_slice = self.m.bit_length() - 1
        self._k = max(1, 256 // self._bits_per_slice)
        self._byte_len = (self.m + 7) // 8
        self._bits = bytearray(self._byte_len)

    @staticmethod
    def _digest(key: str) -> int:
        return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest(), "big")

    def _check(self, value: int) -> bool:
        v = value
        for _ in range(self._k):
            pos = v & self._mask
            byte_idx = pos >> 3
            bit_idx = pos & 7
            if not (self._bits[byte_idx] & (1 << bit_idx)):
                return False
            v >>= self._bits_per_slice
        return True

    def _set(self, value: int) -> None:
        v = value
        for _ in range(self._k):
            pos = v & self._mask
            byte_idx = pos >> 3
            bit_idx = pos & 7
            self._bits[byte_idx] |= 1 << bit_idx
            v >>= self._bits_per_slice

    def add(self, key: str) -> None:
        self._set(self._digest(key))

    def query(self, key: str) -> bool:
        return self._check(self._digest(key))

    def update(self, key: str) -> bool:
        value = self._digest(key)
        if self._check(value):
            return True
        self._set(value)
        return False

    @property
    def load_factor(self) -> float:
        bits_set = sum(b.bit_count() for b in self._bits)
        return bits_set / self.m

    def clear(self) -> None:
        self._bits = bytearray(self._byte_len)


class CacheMetrics(TypedDict):
    hits: int
    misses: int
    hits_by_namespace: dict[str, int]
    misses_by_namespace: dict[str, int]


_cache_metrics: CacheMetrics = {
    "hits": 0,
    "misses": 0,
    "hits_by_namespace": {},
    "misses_by_namespace": {},
}
_cache_metrics_lock = Lock()


def _namespace_for_key(key: str) -> str:
    prefix = key.split(":", 1)[0].strip().lower()
    return prefix or "other"


def _record_cache_hit(key: str) -> None:
    namespace = _namespace_for_key(key)
    with _cache_metrics_lock:
        _cache_metrics["hits"] = int(_cache_metrics["hits"]) + 1
        _cache_metrics["hits_by_namespace"][namespace] = (
            _cache_metrics["hits_by_namespace"].get(namespace, 0) + 1
        )


def _record_cache_miss(key: str) -> None:
    namespace = _namespace_for_key(key)
    with _cache_metrics_lock:
        _cache_metrics["misses"] = int(_cache_metrics["misses"]) + 1
        _cache_metrics["misses_by_namespace"][namespace] = (
            _cache_metrics["misses_by_namespace"].get(namespace, 0) + 1
        )


def get_cache_metrics_snapshot() -> CacheMetrics:
    with _cache_metrics_lock:
        return deepcopy(_cache_metrics)


def reset_cache_metrics() -> None:
    with _cache_metrics_lock:
        _cache_metrics["hits"] = 0
        _cache_metrics["misses"] = 0
        _cache_metrics["hits_by_namespace"] = {}
        _cache_metrics["misses_by_namespace"] = {}


def is_cache_miss(value: object) -> bool:
    return value is SENTINEL


def _default_db_path() -> str:
    _DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return str(_DEFAULT_CACHE_DIR / _DEFAULT_DB_NAME)


def _wrap_value(value: Any) -> str:
    """Serialise *value* to a JSON string, using pickle fallback for non-trivial types."""
    try:
        json.dumps(value)
        return json.dumps({"_t": "json", "v": value}, default=str)
    except (TypeError, ValueError, OverflowError):
        pickled = pickle.dumps(value)
        b64 = base64.b64encode(pickled).decode("ascii")
        return json.dumps({"_t": "pickle", "v": b64})


def _unwrap_value(raw: str) -> Any:
    wrapped = json.loads(raw)
    if not isinstance(wrapped, dict) or "_t" not in wrapped:
        return wrapped
    if wrapped["_t"] == "pickle":
        return pickle.loads(base64.b64decode(wrapped["v"]))
    return wrapped["v"]


class Cache:
    def __init__(
        self,
        db_path: str | None = None,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.db_path = db_path if db_path is not None else _default_db_path()
        self.max_entries = max_entries
        self.con = sqlite3.connect(self.db_path, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.execute("PRAGMA busy_timeout=5000")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS cache"
            " (key TEXT PRIMARY KEY, value BLOB, created_at REAL, expires_at REAL)"
        )
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_created_at ON cache(created_at)"
        )
        self._ensure_expires_column()
        self._entry_count = self._count_entries()
        self._writes_since_maintenance = 0
        self._bloom_check_counter = 0
        self._delete_expired()
        self._init_bloom()

    def _init_bloom(self) -> None:
        capacity = max(1, self._entry_count) * 10
        self._bloom = BloomFilter(capacity)
        rows = self.con.execute("SELECT key FROM cache").fetchall()
        for (key,) in rows:
            self._bloom.add(key)

    def _maybe_grow_bloom(self) -> None:
        self._bloom_check_counter += 1
        interval = max(1, int(self._entry_count * 0.05))
        if self._bloom_check_counter < interval:
            return
        self._bloom_check_counter = 0
        if self._bloom.load_factor > 0.8:
            self._init_bloom()

    def _count_entries(self) -> int:
        row = self.con.execute("SELECT COUNT(*) FROM cache").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def canonicalize_key(key: str) -> str:
        parts = key.strip().split(":", 1)
        namespace = parts[0].strip().lower()
        if len(parts) == 1:
            return namespace
        suffix = " ".join(parts[1].split())
        return f"{namespace}:{suffix}"

    def _ensure_expires_column(self) -> None:
        columns = {
            str(row[1])
            for row in self.con.execute("PRAGMA table_info(cache)").fetchall()
        }
        if "expires_at" not in columns:
            self.con.execute("ALTER TABLE cache ADD COLUMN expires_at REAL")
            self.con.commit()

    def _delete_expired(self) -> int:
        now = time.time()
        cur = self.con.execute(
            "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        deleted = int(cur.rowcount or 0)
        if deleted:
            self._entry_count = max(0, self._entry_count - deleted)
            self._mem.clear()
            self.con.commit()
        return deleted

    def _prune_if_needed(self) -> int:
        if self.max_entries <= 0:
            return 0
        overflow = self._entry_count - self.max_entries
        if overflow <= 0:
            return 0
        cur = self.con.execute(
            "DELETE FROM cache WHERE key IN ("
            "SELECT key FROM cache ORDER BY created_at ASC LIMIT ?"
            ")",
            (overflow,),
        )
        deleted = int(cur.rowcount or 0)
        if deleted:
            self._entry_count = max(0, self._entry_count - deleted)
            self._mem.clear()
            self.con.commit()
        return deleted

    def _delete_key(self, canonical_key: str) -> None:
        cur = self.con.execute("DELETE FROM cache WHERE key = ?", (canonical_key,))
        deleted = int(cur.rowcount or 0)
        if deleted:
            self._entry_count = max(0, self._entry_count - deleted)
            self.con.commit()

    # ── In-memory L1 cache ────────────────────────────────────────────────
    _mem: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        canonical_key = self.canonicalize_key(key)
        if canonical_key in self._mem:
            _record_cache_hit(canonical_key)
            return self._mem[canonical_key]
        if not self._bloom.query(canonical_key):
            _record_cache_miss(canonical_key)
            return None
        row = self.con.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (canonical_key,)
        ).fetchone()
        if row:
            expires_at = row[1]
            if expires_at is not None and float(expires_at) <= time.time():
                self._delete_key(canonical_key)
                _record_cache_miss(canonical_key)
                return None
            value = _unwrap_value(row[0])
            self._mem[canonical_key] = value
            _record_cache_hit(canonical_key)
            return value
        _record_cache_miss(canonical_key)
        return None

    def get_or_sentinel(self, key: str) -> Any:
        canonical_key = self.canonicalize_key(key)
        if canonical_key in self._mem:
            _record_cache_hit(canonical_key)
            return self._mem[canonical_key]
        if not self._bloom.query(canonical_key):
            _record_cache_miss(canonical_key)
            return SENTINEL
        row = self.con.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (canonical_key,)
        ).fetchone()
        if row:
            expires_at = row[1]
            if expires_at is not None and float(expires_at) <= time.time():
                self._delete_key(canonical_key)
                _record_cache_miss(canonical_key)
                return SENTINEL
            value = _unwrap_value(row[0])
            self._mem[canonical_key] = value
            _record_cache_hit(canonical_key)
            return value
        _record_cache_miss(canonical_key)
        return SENTINEL

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        canonical_key = self.canonicalize_key(key)
        self._mem[canonical_key] = value
        self._bloom.add(canonical_key)
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive (greater than zero)")
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        existing = self.con.execute(
            "SELECT 1 FROM cache WHERE key = ?",
            (canonical_key,),
        ).fetchone()
        self.con.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (canonical_key, _wrap_value(value), time.time(), expires_at),
        )
        self.con.commit()
        if existing is None:
            self._entry_count += 1
        self._writes_since_maintenance += 1
        needs_maintenance = (
            self._writes_since_maintenance >= _MAINTENANCE_INTERVAL_WRITES
            or self._entry_count > self.max_entries
        )
        if needs_maintenance:
            self._delete_expired()
            self._prune_if_needed()
            self._writes_since_maintenance = 0
        self._maybe_grow_bloom()

    def clear(self) -> None:
        self.con.execute("DELETE FROM cache")
        self.con.commit()
        self._entry_count = 0
        self._writes_since_maintenance = 0
        self._bloom_check_counter = 0
        self._mem.clear()
        self._init_bloom()

    def close(self) -> None:
        self.con.close()


_cache: Cache | None = None


def _max_entries_from_env() -> int:
    raw = os.getenv("IMPACTGUARD_CACHE_MAX_ENTRIES", str(_DEFAULT_MAX_ENTRIES))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"IMPACTGUARD_CACHE_MAX_ENTRIES must be an integer; received {raw!r}"
        ) from exc


def _cache_path_from_env() -> str | None:
    raw = os.getenv("IMPACTGUARD_CACHE_PATH")
    if raw:
        p = pathlib.Path(raw)
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    return None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        db_path = _cache_path_from_env()
        max_entries = _max_entries_from_env()
        _cache = Cache(db_path=db_path, max_entries=max_entries)
        atexit.register(_cache.close)
    return _cache
