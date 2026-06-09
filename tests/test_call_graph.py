"""Tests for the persistent call graph (call_graph.py)."""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------


class TestIsTestFile:
    def test_test_prefix(self):
        from impactguard.call_graph import _is_test_file

        assert _is_test_file("tests/test_foo.py")
        assert _is_test_file("/src/test_foo.py")
        assert not _is_test_file("src/foo.py")

    def test_test_suffix(self):
        from impactguard.call_graph import _is_test_file

        assert _is_test_file("src/foo_test.py")
        assert not _is_test_file("src/foo.py")

    def test_spec_pattern(self):
        from impactguard.call_graph import _is_test_file

        assert _is_test_file("src/foo.spec.ts")
        assert _is_test_file("src/foo.test.ts")
        assert not _is_test_file("src/foo.ts")

    def test_tests_directory(self):
        from impactguard.call_graph import _is_test_file

        assert _is_test_file("/tests/foo.py")
        assert _is_test_file("src/__tests__/foo.py")
        assert not _is_test_file("src/helpers.py")

    def test_e2e_and_spec_dirs(self):
        from impactguard.call_graph import _is_test_file

        assert _is_test_file("e2e/test_login.py")
        assert _is_test_file("/spec/models.py")


# ---------------------------------------------------------------------------
# _parse_imports_from_source
# ---------------------------------------------------------------------------


class TestParseImportsFromSource:
    def test_import(self):
        from impactguard.call_graph import _parse_imports_from_source

        source = "import os\nimport sys\n"
        result = _parse_imports_from_source(source)
        assert "os" in result
        assert "sys" in result

    def test_from_import(self):
        from impactguard.call_graph import _parse_imports_from_source

        source = "from pathlib import Path\nfrom collections.abc import Iterator\n"
        result = _parse_imports_from_source(source)
        assert "pathlib" in result
        assert "collections.abc" in result

    def test_relative_import_ignored(self):
        from impactguard.call_graph import _parse_imports_from_source

        source = "from . import sibling\nfrom .. import parent\n"
        result = _parse_imports_from_source(source)
        assert result == []

    def test_no_imports(self):
        from impactguard.call_graph import _parse_imports_from_source

        source = "x = 1\ndef foo(): pass\n"
        result = _parse_imports_from_source(source)
        assert result == []

    def test_syntax_error(self):
        from impactguard.call_graph import _parse_imports_from_source

        source = "def foo(:\n"
        result = _parse_imports_from_source(source)
        assert result == []

    def test_duplicates(self):
        from impactguard.call_graph import _parse_imports_from_source

        source = "import os\nimport os\n"
        result = _parse_imports_from_source(source)
        assert result == ["os"]


# ---------------------------------------------------------------------------
# _resolve_import_to_file
# ---------------------------------------------------------------------------


class TestResolveImportToFile:
    def test_simple_module(self):
        from impactguard.call_graph import _resolve_import_to_file

        known = {"os.py"}
        result = _resolve_import_to_file("os", known)
        assert result == ["os.py"]

    def test_nested_module(self):
        from impactguard.call_graph import _resolve_import_to_file

        known = {"a/b/c.py"}
        result = _resolve_import_to_file("a.b.c", known)
        assert "a/b/c.py" in result

    def test_package_init(self):
        from impactguard.call_graph import _resolve_import_to_file

        known = {"a/__init__.py"}
        result = _resolve_import_to_file("a", known)
        assert "a/__init__.py" in result

    def test_no_match(self):
        from impactguard.call_graph import _resolve_import_to_file

        known = {"os.py", "sys.py"}
        result = _resolve_import_to_file("nonexistent", known)
        assert result == []

    def test_partial_prefix_matches(self):
        from impactguard.call_graph import _resolve_import_to_file

        known = {"a.py", "a/b.py"}
        result = _resolve_import_to_file("a.b", known)
        assert "a.py" in result
        assert "a/b.py" in result

    def test_known_files_has_rel_path(self):
        from impactguard.call_graph import _resolve_import_to_file

        known = {"my_package/core.py"}
        result = _resolve_import_to_file("my_package.core", known)
        assert "my_package/core.py" in result


# ---------------------------------------------------------------------------
# CallGraphDB — build & sync
# ---------------------------------------------------------------------------


class TestCallGraphBuild:
    def test_build_single_file(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text(textwrap.dedent("""\
            def hello():
                return 42
        """))

        cg = CallGraphDB(tmp_path)
        try:
            count = cg.build([str(src)])
            assert count == 1
            assert cg.node_count == 1
            assert cg.edge_count == 0
        finally:
            cg.close()

    def test_build_with_call(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text(textwrap.dedent("""\
            def helper():
                return 1
        """))
        main = tmp_path / "main.py"
        main.write_text(textwrap.dedent("""\
            from lib import helper

            def run():
                return helper()
        """))

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])
            assert cg.node_count >= 2

            edges = cg.edge_count
            assert edges >= 1

            callers = cg.get_callers("lib.py:helper")
            assert len(callers) >= 1
        finally:
            cg.close()

    def test_build_nonexistent_file(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            cg.build(["/nonexistent/path.py"])
            assert cg.node_count == 0
            assert cg.edge_count == 0
        finally:
            cg.close()

    def test_build_empty_list(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            count = cg.build([])
            assert count == 0
        finally:
            cg.close()

    def test_build_two_passes(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        util = tmp_path / "util.py"
        util.write_text(textwrap.dedent("""\
            def add(a, b):
                return a + b
        """))
        calc = tmp_path / "calc.py"
        calc.write_text(textwrap.dedent("""\
            from util import add

            def calculate(x):
                return add(x, x)
        """))

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(calc), str(util)])
            assert cg.edge_count >= 1
            callers = cg.get_callers("util.py:add")
            assert any("calculate" in src for src in callers)
        finally:
            cg.close()


class TestCallGraphSync:
    def test_sync_no_changes(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text("def foo(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            count = cg.sync([str(src)])
            assert count == 0
        finally:
            cg.close()

    def test_sync_with_change(self, tmp_path):
        import time

        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text("def foo(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            assert cg.node_count == 1

            # Ensure mtime changes by at least 1 full second
            time.sleep(1.1)
            src.write_text("def foo():\n    return 1\ndef bar():\n    return 2\n")
            count = cg.sync([str(src)])
            assert count == 1
            assert cg.node_count == 2
        finally:
            cg.close()


class TestCallGraphRemoveStale:
    def test_remove_stale_file(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text("def foo(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            assert cg.node_count == 1

            removed = cg.remove_stale(set())
            assert removed == 1
            assert cg.node_count == 0
        finally:
            cg.close()

    def test_remove_stale_noop(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text("def foo(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            removed = cg.remove_stale({str(src.resolve())})
            assert removed == 0
        finally:
            cg.close()

    def test_remove_stale_cleans_imported(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\n")
        main = tmp_path / "main.py"
        main.write_text("from lib import helper\ndef run(): return helper()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])

            lib.unlink()
            removed = cg.remove_stale({str(main.resolve())})
            assert removed == 1

            lib_rel = "lib.py"
            dependents = cg._bfs_dependents([lib_rel], 3)
            assert lib_rel not in dependents
        finally:
            cg.close()


class TestCallGraphStaleness:
    def test_is_stale_on_fresh_db(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            assert cg.is_stale(0) is True
        finally:
            cg.close()

    def test_is_stale_after_build(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "m.py"
        src.write_text("def f(): pass\n")
        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            assert cg.is_stale(3600) is False
            assert cg.is_stale(0) is True
        finally:
            cg.close()

    def test_is_stale_after_sync(self, tmp_path):
        import time

        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "m.py"
        src.write_text("def f(): pass\n")
        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            time.sleep(1)
            src.write_text("def f():\n    pass\n")
            cg.sync([str(src)])
            assert cg.is_stale(3600) is False
        finally:
            cg.close()


# ---------------------------------------------------------------------------
# Query methods
# ---------------------------------------------------------------------------


class TestCallGraphQueries:
    def test_get_callers_direct(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\n")
        main = tmp_path / "main.py"
        main.write_text("from lib import helper\ndef run(): return helper()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])
            callers = cg.get_callers("lib.py:helper")
            assert len(callers) == 1
            assert any("main.py:run" in src for src in callers)
        finally:
            cg.close()

    def test_get_callers_transitive(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        util = tmp_path / "util.py"
        util.write_text("def util_func(): pass\n")
        mid = tmp_path / "mid.py"
        mid.write_text("from util import util_func\ndef mid_func(): return util_func()\n")
        top = tmp_path / "top.py"
        top.write_text("from mid import mid_func\ndef top_func(): return mid_func()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(util), str(mid), str(top)])
            callers = cg.get_callers("util.py:util_func", depth=3)
            assert len(callers) >= 2
        finally:
            cg.close()

    def test_get_callees(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\ndef other(): pass\n")
        main = tmp_path / "main.py"
        main.write_text("from lib import helper\ndef run(): return helper()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])
            callees = cg.get_callees("main.py:run")
            assert len(callees) == 1
        finally:
            cg.close()

    def test_get_impact_radius(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\n")
        main = tmp_path / "main.py"
        main.write_text("from lib import helper\ndef run(): return helper()\ndef unused(): return 1\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])
            radius = cg.get_impact_radius(["lib.py:helper"])
            assert any("main.py:run" in src for src in radius)
        finally:
            cg.close()

    def test_get_call_sites_all(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\n")
        main = tmp_path / "main.py"
        main.write_text("from lib import helper\ndef run(): return helper()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])
            sites = cg.get_call_sites()
            assert len(sites) >= 1
            assert any(s["fqname"] == "lib.py:helper" for s in sites)
        finally:
            cg.close()

    def test_get_call_sites_filtered(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\ndef other(): pass\n")
        main = tmp_path / "main.py"
        main.write_text("from lib import helper, other\ndef run(): return helper() + other()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])
            sites = cg.get_call_sites(target_fqnames={"lib.py:helper"})
            assert all(s["fqname"] == "lib.py:helper" for s in sites)
        finally:
            cg.close()

    def test_get_affected_tests(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\n")
        test = tmp_path / "test_lib.py"
        test.write_text("from lib import helper\ndef test_helper(): helper()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(test)])
            affected = cg.get_affected_tests([str(lib)])
            assert any("test_lib.py" in t for t in affected)
        finally:
            cg.close()

    def test_no_matching_tests(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text("def foo(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            affected = cg.get_affected_tests([str(src)])
            assert affected == []
        finally:
            cg.close()


# ---------------------------------------------------------------------------
# FQN resolution
# ---------------------------------------------------------------------------


class TestResolveCallTarget:
    def test_already_fqname(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            result = cg._resolve_call_target("file.py", "file.py:func")
            assert result == "file.py:func"
        finally:
            cg.close()

    def test_same_file_lookup(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            cg.con.execute(
                "INSERT INTO nodes (id, kind, name, file_path, language, start_line, updated_at) "
                "VALUES ('mod.py:my_func', 'function', 'my_func', 'mod.py', 'python', 1, 1)"
            )
            cg.con.commit()
            result = cg._resolve_call_target("mod.py", "my_func")
            assert result == "mod.py:my_func"
        finally:
            cg.close()

    def test_import_resolution(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            cg.con.execute(
                "INSERT INTO nodes (id, kind, name, file_path, language, start_line, updated_at) "
                "VALUES ('other.py:helper', 'function', 'helper', 'other.py', 'python', 1, 1)"
            )
            cg.con.execute(
                "INSERT INTO file_imports (importer, imported) VALUES ('mod.py', 'other.py')"
            )
            cg.con.commit()
            result = cg._resolve_call_target("mod.py", "helper")
            assert result == "other.py:helper"
        finally:
            cg.close()

    def test_dotted_name_fallback(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            cg.con.execute(
                "INSERT INTO nodes (id, kind, name, file_path, language, start_line, updated_at) "
                "VALUES ('helpers.py:helper', 'function', 'helper', 'helpers.py', 'python', 1, 1)"
            )
            cg.con.commit()
            result = cg._resolve_call_target("mod.py", "helpers.helper")
            assert result == "helpers.py:helper"
        finally:
            cg.close()

    def test_empty_name(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            result = cg._resolve_call_target("mod.py", "")
            assert result == ""
        finally:
            cg.close()

    def test_no_resolution(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            result = cg._resolve_call_target("mod.py", "nonexistent")
            assert result == "nonexistent"
        finally:
            cg.close()


# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------


class TestCallGraphLifecycle:
    def test_close(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        cg.close()
        assert cg.con is not None

    def test_clear(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text("def foo(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            assert cg.node_count > 0
            cg.clear()
            assert cg.node_count == 0
            assert cg.edge_count == 0
        finally:
            cg.close()

    def test_stats(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "module.py"
        src.write_text("def foo(): pass\ndef bar(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            stats = cg.stats()
            assert stats["nodes"] == 2
            assert stats["edges"] == 0
            assert stats["files"] == 1
            assert stats["dangling_edge_targets"] == 0
            assert "db_path" in stats
        finally:
            cg.close()

    def test_stats_dangling_edges_detected(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\n")
        main = tmp_path / "main.py"
        main.write_text("from lib import helper\ndef run(): return helper()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(main)])
            assert cg.stats()["dangling_edge_targets"] == 0

            lib.unlink()
            cg.remove_stale({str(main.resolve())})

            dangling = cg.stats()["dangling_edge_targets"]
            assert dangling == 1, (
                f"Expected 1 dangling edge (main.py:run → lib.py:helper, lib.py removed), "
                f"got {dangling}"
            )
        finally:
            cg.close()

    def test_db_file_created(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        db_path = cg.db_path
        cg.close()
        assert db_path.exists()
