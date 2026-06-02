"""Cached AST parsing and file-reading wrappers for ImpactGuard.

These wrappers provide transparent, best-effort caching via
:mod:`impactguard.cache` so that repeated analysis runs over the same
files are significantly faster.

Internal cache keys
-------------------
* ``ast:<sha256(source)>`` — pickled ``ast.Module`` trees.
* ``file:<resolved_path>:<size>:<mtime_ns>`` — cached ``Path.read_text()``
  results.  Deriving the key from mtime + size means a modified file
  automatically gets a new cache entry without invalidation logic.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


def _file_key(path: Path) -> str:
    resolved = path.resolve()
    try:
        st = resolved.stat()
        return f"file:{resolved}:{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return f"file:{resolved}:fallback"


def cached_read_text(path: str | Path) -> str:
    """Read a file's text content, caching the result opportunistically.

    The cache key includes the file's resolved path, size, and *mtime* so
    that modifications on disk automatically generate a fresh entry.
    """
    p = Path(path)
    key = _file_key(p)
    from .cache import get_cache

    cache = get_cache()
    result = cache.get(key)
    if result is not None:
        return result
    text = p.read_text()
    cache.set(key, text)
    return text


def cached_ast_parse(source: str) -> ast.Module:
    """Parse *source* into an AST, caching the result.

    The cache key is ``ast:<sha256(source)>``, so repeatedly parsing the
    same source (across runs) reuses the pickled AST tree.
    """
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    key = f"ast:{digest}"
    from .cache import get_cache

    cache = get_cache()
    result = cache.get(key)
    if result is not None:
        return result
    tree = ast.parse(source)
    cache.set(key, tree)
    return tree
