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
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Try to import the Rust fast-walk extension; fall back to pure Python.
try:
    from fast_walk import walk_unordered as _rust_walk  # type: ignore[import-untyped]

    def _rust_fast_walk(tree: ast.Module) -> list[ast.AST]:
        return list(_rust_walk(tree))

    _fast_walk_impl = _rust_fast_walk
    _WALK_BACKEND = "rust"
except ImportError:
    _WALK_BACKEND = "python"


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


def fast_walk(tree: ast.Module) -> list[ast.AST]:
    """Fast replacement for ``list(ast.walk(tree))``.

    When the optional ``fast-walk`` Rust extension is installed, delegates
    to its CPython-inline traversal (~30x faster).  Otherwise falls back
    to a pure-Python implementation (~1.5x faster than stdlib).

    .. note::

       **Order is DFS, not BFS** — do not depend on parent-before-child
       ordering.  ``ast.walk()`` is BFS; this function is stack-based DFS
       (reversed).  The set of visited nodes is identical, but the
       iteration order differs.  Current consumers (``extract_signatures``,
       ``class_hierarchy``, ``call_graph``) are order-independent.
    """
    if _WALK_BACKEND == "rust":
        return _fast_walk_impl(tree)
    return _py_fast_walk(tree)


def _py_fast_walk(tree: ast.Module) -> list[ast.AST]:
    """Pure-Python fast walk — list-based, no generators."""
    todo = [tree]
    out: list[ast.AST] = []
    while todo:
        node = todo.pop()
        out.append(node)
        for field_name in node._fields:
            field_value = getattr(node, field_name, None)
            if isinstance(field_value, list):
                for item in field_value:
                    if isinstance(item, ast.AST):
                        todo.append(item)
            elif isinstance(field_value, ast.AST):
                todo.append(field_value)
    return out


def cached_ast_parse(source: str) -> ast.Module:
    """Parse *source* into an AST, caching the result.

    The cache key is ``ast2:<sha256(source)>`` so repeatedly parsing the
    same source (across runs) reuses the cached AST tree.  The ``2``
    suffix orphans entries written by earlier versions that used
    ``ast.dump()`` serialisation (which produced broken round-trips).
    """
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    key = f"ast2:{digest}"
    from .cache import get_cache

    cache = get_cache()
    result = cache.get(key)
    if result is not None:
        return result
    tree = ast.parse(source)
    cache.set(key, tree)
    return tree
