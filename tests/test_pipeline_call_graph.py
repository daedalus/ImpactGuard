"""End-to-end tests for call graph integration in the pipeline."""

import json
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPipelineWithCallGraph:
    def test_quick_check_with_call_graph(self, tmp_path):
        from impactguard.pipeline import quick_check

        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        lib_old = old_dir / "lib.py"
        lib_old.write_text(textwrap.dedent("""\
            def helper(x):
                return x + 1
        """))

        lib_new = new_dir / "lib.py"
        lib_new.write_text(textwrap.dedent("""\
            def helper(x, y=0):
                return x + y
        """))

        main_old = old_dir / "main.py"
        main_old.write_text(textwrap.dedent("""\
            from lib import helper

            def run():
                return helper(1)
        """))

        main_new = new_dir / "main.py"
        main_new.write_text(textwrap.dedent("""\
            from lib import helper

            def run():
                return helper(1, 2)
        """))

        with mock.patch.dict("os.environ", {"SKIP_SIGNATURE_HOOK": "1"}):
            result = quick_check(
                str(old_dir),
                str(new_dir),
                use_call_graph=True,
                conservative=False,
            )

        comparison = result.get("comparison", {})
        breaking = comparison.get("breaking", [])
        nonbreaking = comparison.get("nonbreaking", [])
        all_changes = breaking + nonbreaking
        assert any("helper" in b for b in all_changes)

    def test_call_graph_impact_radius_in_pipeline(self, tmp_path):
        from impactguard.pipeline import run_pipeline

        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        lib_old = old_dir / "lib.py"
        lib_old.write_text(textwrap.dedent("""\
            def helper():
                return 1
        """))
        lib_new = new_dir / "lib.py"
        lib_new.write_text(textwrap.dedent("""\
            def helper():
                return 42
        """))

        main_old = old_dir / "main.py"
        main_old.write_text(textwrap.dedent("""\
            from lib import helper

            def run():
                return helper()
        """))
        main_new = new_dir / "main.py"
        main_new.write_text(textwrap.dedent("""\
            from lib import helper

            def run():
                return helper()
        """))

        old_sigs_dir = tmp_path / "old_sigs"
        new_sigs_dir = tmp_path / "new_sigs"
        calls_dir = tmp_path / "calls"
        old_sigs_dir.mkdir()
        new_sigs_dir.mkdir()
        calls_dir.mkdir()

        result = run_pipeline(
            old_files=[str(lib_old), str(main_old)],
            new_files=[str(lib_new), str(main_new)],
            old_sigs_path=str(old_sigs_dir),
            new_sigs_path=str(new_sigs_dir),
            calls_path=str(calls_dir),
            output_dir=str(tmp_path / "out"),
            use_call_graph=True,
            conservative=False,
        )

        impact = result.get("impact", [])
        assert isinstance(impact, list)

    def test_pipeline_with_call_graph_sync(self, tmp_path):
        import time

        from impactguard.call_graph import CallGraphDB

        src = tmp_path / "mod.py"
        src.write_text("def foo(): pass\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(src)])
            assert cg.node_count == 1
            assert cg.edge_count == 0

            time.sleep(1.1)
            src.write_text("def foo():\n    return 1\ndef bar():\n    return 2\n")
            cg.sync([str(src)])
            assert cg.node_count == 2
        finally:
            cg.close()

    def test_pipeline_call_graph_no_files(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        cg = CallGraphDB(tmp_path)
        try:
            count = cg.build([])
            assert count == 0
            assert cg.node_count == 0
            assert cg.edge_count == 0
        finally:
            cg.close()

    def test_affected_tests_via_call_graph(self, tmp_path):
        from impactguard.call_graph import CallGraphDB

        lib = tmp_path / "lib.py"
        lib.write_text("def helper(): pass\n")

        test_file = tmp_path / "tests" / "test_lib.py"
        test_file.parent.mkdir()
        test_file.write_text("from lib import helper\ndef test_helper(): helper()\n")

        cg = CallGraphDB(tmp_path)
        try:
            cg.build([str(lib), str(test_file)])
            affected = cg.get_affected_tests([str(lib)])
            assert affected == ["tests/test_lib.py"]
        finally:
            cg.close()
