"""Persistent call graph for ImpactGuard.

Stores extracted call sites, function nodes, and file-level import
dependencies in a local SQLite database so that subsequent runs can
query the pre-indexed graph instead of re-parsing source files.

Database location: ``<project_root>/.impactguard/call_graph.db``
"""

import ast
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from ._logging import get_logger

_log = get_logger(__name__)

CACHE_DIR = ".impactguard"
DB_FILENAME = "call_graph.db"

EDGE_CALLS = "calls"
EDGE_IMPORTS = "imports"

_TEST_FILE_PATTERNS = (
    "test_",
    "_test",
    ".spec.",
    ".test.",
    "/tests/",
    "/__tests__/",
    "/e2e/",
    "/spec/",
    "/test_",
    "_test.py",
    "_spec.",
)


def _is_test_file(path: str) -> bool:
    lp = path.lower()
    for pat in _TEST_FILE_PATTERNS:
        if pat in lp:
            return True
    return False


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'function',
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'python',
    start_line INTEGER DEFAULT 0,
    end_line INTEGER DEFAULT 0,
    signature TEXT,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_file TEXT NOT NULL,
    target_file TEXT NOT NULL,
    lineno INTEGER DEFAULT 0,
    col INTEGER DEFAULT 0,
    args INTEGER DEFAULT 0,
    kwargs TEXT DEFAULT '[]',
    has_starargs INTEGER DEFAULT 0,
    has_kwargs INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source, kind);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target, kind);
CREATE INDEX IF NOT EXISTS idx_edges_target_file ON edges(target_file);

CREATE TABLE IF NOT EXISTS file_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    importer TEXT NOT NULL,
    imported TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fi_importer ON file_imports(importer);
CREATE INDEX IF NOT EXISTS idx_fi_imported ON file_imports(imported);

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'python',
    size INTEGER DEFAULT 0,
    modified_at INTEGER NOT NULL,
    indexed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Import resolution helpers
# ---------------------------------------------------------------------------


def _parse_imports_from_source(source: str) -> list[str]:
    """Return list of dotted module names imported in *source*."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
    return sorted(modules)


def _resolve_import_to_file(
    module_name: str, known_files: set[str]
) -> list[str]:
    """Try to resolve a dotted module name to one or more file paths.

    Searches ``<project_root>`` for candidate files — ``<module>.py``,
    ``<module>/__init__.py``, and path-separator variants.  For dotted
    names like ``a.b.c`` this checks every prefix in case of namespace
    packages or deeply nested modules.
    """
    candidates: list[str] = []
    parts = module_name.split(".")
    for i in range(1, len(parts) + 1):
        prefix = "/".join(parts[:i])
        guesses = [
            f"{prefix}.py",
            f"{prefix}/__init__.py",
        ]
        for guess in guesses:
            rel_guess = str(Path(guess))
            if rel_guess in known_files:
                candidates.append(rel_guess)
    return candidates


# ---------------------------------------------------------------------------
# CallGraphDB
# ---------------------------------------------------------------------------


class CallGraphDB:
    """Persistent call graph backed by a local SQLite database.

    Typical usage::

        cg = CallGraphDB("/path/to/project")
        cg.build([...files...])       # first-time index
        cg.sync([...files...])        # incremental update
        callers = cg.get_callers("file.py:func")
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        cache_dir = self.project_root / CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = cache_dir / DB_FILENAME

        self.con = sqlite3.connect(str(self.db_path))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(_SCHEMA_SQL)

    # ------------------------------------------------------------------
    # Build / Sync
    # ------------------------------------------------------------------

    def _relativize(self, file_path: str) -> str:
        try:
            return str(Path(file_path).relative_to(self.project_root))
        except ValueError:
            return file_path

    def build(self, files: list[str]) -> int:
        """Full build: index all *files* into the call graph.

        Three-pass strategy ensures imports are available before
        cross-file call target resolution runs.

        Args:
            files: Absolute paths to source files to index.

        Returns:
            Number of files actually indexed.
        """
        count = 0
        for f in files:
            try:
                self._index_file(f)
                count += 1
            except Exception:
                _log.warning("Failed to index '%s'", f, exc_info=True)
        self.con.commit()
        for f in files:
            try:
                self._index_file_imports(f)
            except Exception:
                _log.warning("Failed to index imports for '%s'", f, exc_info=True)
        self.con.commit()
        for f in files:
            try:
                rel_path = self._relativize(f)
                self._index_calls(f, rel_path)
            except Exception:
                _log.warning("Failed to index calls for '%s'", f, exc_info=True)
        self.con.commit()
        self._record_build()
        return count

    def _record_build(self) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('built_at', ?)",
            (str(int(time.time())),),
        )
        self.con.commit()

    def is_stale(self, max_seconds: int = 3600) -> bool:
        """Return *True* when the DB was last built more than *max_seconds* ago.

        A stale DB may contain edges that reference outdated signatures,
        particularly after switching branches or after a long gap between
        ``--use-call-graph`` runs.  Callers should force a full rebuild
        when this returns *True*.
        """
        row = self.con.execute(
            "SELECT value FROM metadata WHERE key = 'built_at'"
        ).fetchone()
        if row is None:
            return True
        try:
            built_at = int(row["value"])
        except (ValueError, TypeError):
            return True
        return (time.time() - built_at) > max_seconds

    def sync(self, files: list[str]) -> int:
        """Incremental sync: only re-index files whose content changed.

        Three-pass strategy (signatures → imports → calls) mirrors
        :meth:`build` so that cross-file call resolution has access to
        the ``file_imports`` table.

        Args:
            files: Absolute paths to candidate source files.

        Returns:
            Number of files that were re-indexed.
        """
        changed = [f for f in files if self._is_stale(f)]
        if not changed:
            return 0

        for f in changed:
            try:
                self._index_file(f)
            except Exception:
                _log.warning("Failed to sync '%s'", f, exc_info=True)
        self.con.commit()
        for f in changed:
            try:
                self._index_file_imports(f)
            except Exception:
                _log.warning("Failed to sync imports for '%s'", f, exc_info=True)
        self.con.commit()
        for f in changed:
            try:
                rel_path = self._relativize(f)
                self._index_calls(f, rel_path)
            except Exception:
                _log.warning("Failed to sync calls for '%s'", f, exc_info=True)
        self.con.commit()
        self._record_build()
        return len(changed)

    def remove_stale(self, active_files: set[str]) -> int:
        """Remove DB entries for files no longer on disk.

        Args:
            active_files: Set of file paths that still exist (absolute or
                relative to the project root — both are accepted).

        Returns:
            Number of stale files cleaned up.
        """
        rows = self.con.execute("SELECT path FROM files").fetchall()
        db_files = {row["path"] for row in rows}
        active = {self._relativize(p) for p in active_files}
        stale = db_files - active
        if not stale:
            return 0
        for f in stale:
            self._remove_file(f)
            self.con.execute(
                "DELETE FROM file_imports WHERE imported = ?", (f,)
            )
        self.con.commit()
        return len(stale)

    def filter_stale(self, files: list[str]) -> list[str]:
        """Return only files whose content has changed since last build/sync.

        Args:
            files: Absolute paths to candidate source files.

        Returns:
            Subset of *files* whose mtime or existence differs from the DB.
        """
        return [f for f in files if self._is_stale(f)]

    # ------------------------------------------------------------------
    # Queries: call graph
    # ------------------------------------------------------------------

    def get_callers(
        self, fqname: str, depth: int = 1
    ) -> dict[str, int]:
        """Return direct and transitive callers of *fqname*.

        Returns ``{caller_fqname: hop_distance}``.
        """
        return self._bfs_backward(fqname, EDGE_CALLS, depth)

    def get_callees(
        self, fqname: str, depth: int = 1
    ) -> dict[str, int]:
        """Return direct and transitive callees of *fqname*.

        Returns ``{callee_fqname: hop_distance}``.
        """
        return self._bfs_forward(fqname, EDGE_CALLS, depth)

    def get_impact_radius(
        self, fqnames: list[str], depth: int = 3
    ) -> dict[str, int]:
        """Return all nodes transitively impacted by changes to *fqnames*.

        Follows **all** edge kinds (calls, imports, references) except
        containment, matching CodeGraph's ``getImpactRadius`` semantics.

        Returns ``{affected_fqname: hop_distance}``.
        """
        result: dict[str, int] = {}
        for fqname in fqnames:
            impacted = self._bfs_impact(fqname, depth)
            for k, v in impacted.items():
                if k not in result or v < result[k]:
                    result[k] = v
        return result

    def get_call_sites(
        self, target_fqnames: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Export stored call edges in ImpactGuard's call-site JSON format.

        Args:
            target_fqnames: Optional set of callee FQNs to filter by.
                When *None*, all call edges are exported.

        Returns:
            List of call-site dicts matching the schema consumed by
            ``impact_analysis.load_calls``.
        """
        if target_fqnames:
            placeholders = ",".join("?" for _ in target_fqnames)
            rows = self.con.execute(
                f"""SELECT source, target, source_file, lineno, col,
                           args, kwargs, has_starargs, has_kwargs
                    FROM edges
                    WHERE kind = ? AND target IN ({placeholders})""",
                (EDGE_CALLS, *target_fqnames),
            ).fetchall()
        else:
            rows = self.con.execute(
                """SELECT source, target, source_file, lineno, col,
                          args, kwargs, has_starargs, has_kwargs
                   FROM edges WHERE kind = ?""",
                (EDGE_CALLS,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for r in rows:
            caller_name = (
                r["source"].split(":", 1)[-1]
                if ":" in r["source"]
                else r["source"]
            )
            result.append(
                {
                    "fqname": r["target"],
                    "file": r["source_file"],
                    "lineno": r["lineno"],
                    "col": r["col"],
                    "args": r["args"],
                    "kwargs": json.loads(r["kwargs"] or "[]"),
                    "starargs": bool(r["has_starargs"]),
                    "kwargs_any": bool(r["has_kwargs"]),
                    "caller": caller_name,
                }
            )
        return result

    def get_affected_tests(
        self, file_paths: list[str], depth: int = 5
    ) -> list[str]:
        """Return test files transitively importing from any of *file_paths*.

        Performs BFS on the ``file_imports`` table (importer → imported),
        filtering results to paths that match test-file patterns.

        Returns sorted list of test file paths.
        """
        rel_paths = [self._relativize(p) for p in file_paths]
        dependents = self._bfs_dependents(rel_paths, depth)
        tests = sorted(f for f in dependents if _is_test_file(f))
        return tests

    # ------------------------------------------------------------------
    # Internal: indexing
    # ------------------------------------------------------------------

    def _is_stale(self, file_path: str) -> bool:
        path = Path(file_path)
        if not path.exists():
            return True
        try:
            mtime = int(path.stat().st_mtime)
            rel_path = self._relativize(file_path)
            row = self.con.execute(
                "SELECT modified_at FROM files WHERE path = ?",
                (rel_path,),
            ).fetchone()
            if row is None:
                return True
            return row["modified_at"] != mtime
        except OSError:
            return True

    def _index_file(self, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            self._remove_file(file_path)
            return

        content = path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        mtime = int(path.stat().st_mtime)
        size = len(content)

        try:
            rel_path = str(path.relative_to(self.project_root))
        except ValueError:
            rel_path = file_path

        # Remove stale data for this file
        self._remove_file(rel_path)

        # -- Signatures → nodes -- (calls and imports indexed separately
        # by build / sync so that file_imports is available for resolution)
        self._index_signatures(file_path, rel_path)

        # -- File record --
        self.con.execute(
            """INSERT OR REPLACE INTO files
               (path, content_hash, language, size, modified_at, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rel_path, content_hash, "python", size, mtime, int(time.time())),
        )

    def _index_file_imports(self, file_path: str) -> None:
        rel_path = self._relativize(file_path)
        path = Path(file_path)
        if not path.exists():
            return
        content = path.read_bytes()
        self._index_imports(rel_path, content.decode("utf-8", errors="replace"))

    def _index_signatures(self, file_path: str, rel_path: str | None = None) -> None:
        from .extract_signatures import extract as extract_sigs

        sigs = extract_sigs([file_path], base_path=str(self.project_root))
        for sig in sigs:
            fqname = sig.get("fqname", "")
            if not fqname:
                continue
            self.con.execute(
                """INSERT OR REPLACE INTO nodes
                   (id, kind, name, file_path, language, start_line, end_line, signature, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fqname,
                    sig.get("kind", "function"),
                    sig.get("name", ""),
                    rel_path or sig.get("file", file_path),
                    "python",
                    sig.get("lineno", 0),
                    sig.get("end_lineno", 0),
                    json.dumps(sig),
                    int(time.time()),
                ),
            )

    def _resolve_call_target(self, rel_path: str, name: str) -> str:
        if not name:
            return ""
        if ":" in name:
            return name
        same = self.con.execute(
            "SELECT id FROM nodes WHERE file_path = ? AND name = ?",
            (rel_path, name),
        ).fetchone()
        if same:
            return same["id"]
        imported = self.con.execute(
            """SELECT fi.imported FROM file_imports fi
               WHERE fi.importer = ?""",
            (rel_path,),
        ).fetchall()
        for row in imported:
            row2 = self.con.execute(
                "SELECT id FROM nodes WHERE file_path = ? AND name = ?",
                (row["imported"], name),
            ).fetchone()
            if row2:
                return row2["id"]
        if "." in name:
            parts = name.rsplit(".", 1)
            if len(parts) == 2:
                mod_prefix, func_name = parts
                for cand in (f"{mod_prefix}.py", f"{mod_prefix}/__init__.py"):
                    row = self.con.execute(
                        "SELECT id FROM nodes WHERE (file_path = ? OR file_path LIKE ?) AND name = ?",
                        (cand, f"%/{cand}", func_name),
                    ).fetchone()
                    if row:
                        return row["id"]
        return name

    def _index_calls(self, file_path: str, rel_path: str | None = None) -> None:
        from .analyze_module import analyze as analyze_calls

        try:
            result = analyze_calls(file_path)
        except Exception:
            _log.debug("analyze_module failed for '%s', trying extract_calls", file_path)
            result = self._fallback_extract_calls(file_path)

        if not result or "calls" not in result:
            return

        effective_path = rel_path or file_path

        for call in result["calls"]:
            callee_fqname = self._resolve_call_target(effective_path, call.get("fqname", ""))
            if not callee_fqname:
                continue

            caller_name = call.get("caller")
            if caller_name:
                source = f"{effective_path}:{caller_name}"
            else:
                source = f"{effective_path}:<module>"

            self.con.execute(
                """INSERT INTO edges
                   (source, target, kind, source_file, target_file, lineno, col,
                    args, kwargs, has_starargs, has_kwargs)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source,
                    callee_fqname,
                    EDGE_CALLS,
                    effective_path,
                    self._relativize(call.get("file", file_path)),
                    call.get("lineno", 0),
                    call.get("col", 0),
                    call.get("args", 0),
                    json.dumps(call.get("kwargs", [])),
                    1 if call.get("starargs") else 0,
                    1 if call.get("kwargs_any") else 0,
                ),
            )

    def _fallback_extract_calls(
        self, file_path: str
    ) -> dict[str, Any] | None:
        from pathlib import Path as _Path

        from .extract_calls import extract as fallback_extract

        calls = fallback_extract(_Path(file_path))
        if not calls:
            return None
        return {"calls": calls, "file": file_path}

    def _index_imports(self, file_path: str, source: str) -> None:
        module_names = _parse_imports_from_source(source)

        # Collect known files for resolution
        known_rows = self.con.execute("SELECT path FROM files").fetchall()
        known_files = {r["path"] for r in known_rows}
        known_files.add(file_path)

        for mod in module_names:
            resolved = _resolve_import_to_file(
                mod, known_files
            )
            for target_path in resolved:
                self.con.execute(
                    "INSERT OR IGNORE INTO file_imports (importer, imported) VALUES (?, ?)",
                    (file_path, target_path),
                )

    def _remove_file(self, file_path: str) -> None:
        self.con.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
        self.con.execute("DELETE FROM edges WHERE source_file = ?", (file_path,))
        self.con.execute("DELETE FROM file_imports WHERE importer = ?", (file_path,))
        self.con.execute("DELETE FROM files WHERE path = ?", (file_path,))

    # ------------------------------------------------------------------
    # Internal: BFS helpers
    # ------------------------------------------------------------------

    def _bfs_backward(
        self, start: str, kind: str, depth: int
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        frontier = {start}
        for hop in range(1, depth + 1):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self.con.execute(
                f"SELECT DISTINCT source FROM edges WHERE target IN ({placeholders}) AND kind = ?",
                (*frontier, kind),
            ).fetchall()
            next_frontier: set[str] = set()
            for (source,) in rows:
                if source not in result and source != start:
                    result[source] = hop
                    next_frontier.add(source)
            frontier = next_frontier
        return result

    def _bfs_forward(
        self, start: str, kind: str, depth: int
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        frontier = {start}
        for hop in range(1, depth + 1):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self.con.execute(
                f"SELECT DISTINCT target FROM edges WHERE source IN ({placeholders}) AND kind = ?",
                (*frontier, kind),
            ).fetchall()
            next_frontier: set[str] = set()
            for (target,) in rows:
                if target not in result and target != start:
                    result[target] = hop
                    next_frontier.add(target)
            frontier = next_frontier
        return result

    def _bfs_impact(self, start: str, depth: int) -> dict[str, int]:
        """BFS following ALL incoming edges (like CodeGraph getImpactRadius)."""
        result: dict[str, int] = {}
        frontier = {start}
        for hop in range(1, depth + 1):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self.con.execute(
                f"SELECT DISTINCT source FROM edges WHERE target IN ({placeholders})",
                (*frontier,),
            ).fetchall()
            next_frontier: set[str] = set()
            for (source,) in rows:
                if source not in result and source != start:
                    result[source] = hop
                    next_frontier.add(source)
            frontier = next_frontier
        return result

    def _bfs_dependents(
        self, file_paths: list[str], depth: int
    ) -> set[str]:
        result: set[str] = set()
        frontier = set(file_paths)
        for _hop in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self.con.execute(
                f"SELECT DISTINCT importer FROM file_imports WHERE imported IN ({placeholders})",
                (*frontier,),
            ).fetchall()
            next_frontier: set[str] = set()
            for (importer,) in rows:
                if importer not in result and importer not in file_paths:
                    result.add(importer)
                    next_frontier.add(importer)
            frontier = next_frontier
        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self.con.close()

    def clear(self) -> None:
        self.con.executescript(
            "DELETE FROM nodes; DELETE FROM edges; DELETE FROM file_imports; DELETE FROM files;"
        )
        self.con.commit()

    @property
    def node_count(self) -> int:
        row = self.con.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()
        return row["c"] if row else 0

    @property
    def edge_count(self) -> int:
        row = self.con.execute("SELECT COUNT(*) AS c FROM edges").fetchone()
        return row["c"] if row else 0

    def stats(self) -> dict[str, Any]:
        dangling = self.con.execute(
            """SELECT COUNT(*) AS c FROM edges e
               LEFT JOIN nodes n ON e.target = n.id
               WHERE n.id IS NULL"""
        ).fetchone()["c"]

        if dangling:
            _log.warning(
                "Call graph has %d dangling edge target(s) — edges whose target FQN "
                "does not match any node in the DB. BFS queries skip them silently.",
                dangling,
            )

        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "dangling_edge_targets": dangling,
            "files": self.con.execute(
                "SELECT COUNT(*) AS c FROM files"
            ).fetchone()["c"],
            "db_path": str(self.db_path),
        }
