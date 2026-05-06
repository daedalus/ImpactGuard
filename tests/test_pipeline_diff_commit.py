"""Tests for run_pipeline_diff and run_pipeline_commit."""

import difflib
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_unified_diff(old_src: str, new_src: str, filename: str = "module.py") -> str:
    """Create a minimal unified diff string from two source strings."""
    old_lines = old_src.splitlines(keepends=True)
    new_lines = new_src.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )
    return "".join(diff)


def run_cli(args: list[str]) -> int:
    """Run the ImpactGuard CLI with the given arguments."""
    from impactguard.__main__ import main as cli_main

    old_argv = sys.argv[:]
    sys.argv = ["impactguard"] + args
    try:
        return cli_main() or 0
    except SystemExit as exc:
        return exc.code or 0
    finally:
        sys.argv = old_argv


# ---------------------------------------------------------------------------
# _parse_unified_diff
# ---------------------------------------------------------------------------

class TestParseUnifiedDiff:
    def test_basic_change(self):
        from impactguard.pipeline import _parse_unified_diff

        old = "def foo(x):\n    return x\n"
        new = "def foo(x, y=0):\n    return x + y\n"
        diff = _make_unified_diff(old, new)
        result = _parse_unified_diff(diff)
        assert "module.py" in result
        old_content, new_content = result["module.py"]
        assert "def foo(x)" in old_content
        assert "def foo(x, y=0)" in new_content

    def test_added_file(self):
        from impactguard.pipeline import _parse_unified_diff

        diff = textwrap.dedent("""\
            --- /dev/null
            +++ b/new_file.py
            @@ -0,0 +1,3 @@
            +def bar():
            +    pass
            +
        """)
        result = _parse_unified_diff(diff)
        assert "new_file.py" in result
        old_content, new_content = result["new_file.py"]
        assert old_content.strip() == ""
        assert "def bar" in new_content

    def test_deleted_file(self):
        from impactguard.pipeline import _parse_unified_diff

        diff = textwrap.dedent("""\
            --- a/old_file.py
            +++ /dev/null
            @@ -1,3 +0,0 @@
            -def baz():
            -    pass
            -
        """)
        result = _parse_unified_diff(diff)
        # deleted file -> new_name is None, so key is old name
        assert "old_file.py" in result
        old_content, new_content = result["old_file.py"]
        assert "def baz" in old_content
        assert new_content.strip() == ""

    def test_non_python_files_excluded(self):
        from impactguard.pipeline import _parse_unified_diff

        diff = textwrap.dedent("""\
            --- a/README.md
            +++ b/README.md
            @@ -1 +1 @@
            -old line
            +new line
        """)
        result = _parse_unified_diff(diff)
        assert len(result) == 0

    def test_unsupported_files_excluded_makefile(self):
        """Makefile, HTML, and other unsupported types are always excluded."""
        from impactguard.pipeline import _parse_unified_diff

        diff = textwrap.dedent("""\
            --- a/Makefile
            +++ b/Makefile
            @@ -1 +1 @@
            -all:
            +all: build
            --- a/index.html
            +++ b/index.html
            @@ -1 +1 @@
            -<html>
            +<html lang="en">
        """)
        result = _parse_unified_diff(diff)
        assert len(result) == 0

    def test_typescript_file_included(self):
        """TypeScript files with a registered extractor are captured."""
        from impactguard.pipeline import _parse_unified_diff

        diff = textwrap.dedent("""\
            --- a/api.ts
            +++ b/api.ts
            @@ -1,3 +1,3 @@
            -function greet(name: string): string {
            +function greet(name: string, greeting: string = 'Hello'): string {
                 return name;
             }
        """)
        result = _parse_unified_diff(diff)
        assert "api.ts" in result
        old_content, new_content = result["api.ts"]
        assert "greet(name: string)" in old_content
        assert "greeting: string" in new_content

    def test_mixed_diff_captures_supported_only(self):
        """A diff touching Python, TypeScript, Makefile, and HTML captures only supported files."""
        from impactguard.pipeline import _parse_unified_diff

        py_diff = _make_unified_diff("def foo(): pass\n", "def foo(x): pass\n", "mod.py")
        ts_diff = textwrap.dedent("""\
            --- a/lib.ts
            +++ b/lib.ts
            @@ -1 +1 @@
            -export function bar() {}
            +export function bar(x: number) {}
        """)
        make_diff = textwrap.dedent("""\
            --- a/Makefile
            +++ b/Makefile
            @@ -1 +1 @@
            -build:
            +build: test
        """)
        html_diff = textwrap.dedent("""\
            --- a/index.html
            +++ b/index.html
            @@ -1 +1 @@
            -<title>old</title>
            +<title>new</title>
        """)
        result = _parse_unified_diff(py_diff + ts_diff + make_diff + html_diff)
        assert "mod.py" in result
        assert "lib.ts" in result
        assert "Makefile" not in result
        assert "index.html" not in result

    def test_multiple_files(self):
        from impactguard.pipeline import _parse_unified_diff

        old_a = "def a(): pass\n"
        new_a = "def a(x): pass\n"
        old_b = "def b(): pass\n"
        new_b = "def b(y): pass\n"
        diff = _make_unified_diff(old_a, new_a, "mod_a.py")
        diff += _make_unified_diff(old_b, new_b, "mod_b.py")
        result = _parse_unified_diff(diff)
        assert "mod_a.py" in result
        assert "mod_b.py" in result

    def test_empty_diff_returns_empty_dict(self):
        from impactguard.pipeline import _parse_unified_diff

        result = _parse_unified_diff("")
        assert result == {}


# ---------------------------------------------------------------------------
# run_pipeline_diff
# ---------------------------------------------------------------------------

class TestRunPipelineDiff:
    def test_basic_diff_runs_pipeline(self, tmp_path):
        from impactguard.pipeline import run_pipeline_diff

        old_src = "def foo(x):\n    return x\n"
        new_src = "def foo(x, y=0):\n    return x + y\n\ndef bar():\n    pass\n"
        diff_content = _make_unified_diff(old_src, new_src)
        diff_file = tmp_path / "changes.patch"
        diff_file.write_text(diff_content)

        result = run_pipeline_diff(str(diff_file))
        assert isinstance(result, dict)
        # Should have comparison or signatures key at minimum
        assert "comparison" in result or "signatures" in result

    def test_diff_with_breaking_change(self, tmp_path):
        from impactguard.pipeline import run_pipeline_diff

        old_src = "def process(data, flag):\n    return data\n"
        new_src = "def process(data, flag, extra):\n    return data\n"
        diff_content = _make_unified_diff(old_src, new_src)
        diff_file = tmp_path / "breaking.patch"
        diff_file.write_text(diff_content)

        result = run_pipeline_diff(str(diff_file))
        assert isinstance(result, dict)

    def test_missing_diff_file_raises(self, tmp_path):
        from impactguard.pipeline import run_pipeline_diff

        with pytest.raises(FileNotFoundError):
            run_pipeline_diff(str(tmp_path / "nonexistent.patch"))

    def test_no_python_files_in_diff_raises(self, tmp_path):
        from impactguard.pipeline import run_pipeline_diff

        diff_content = textwrap.dedent("""\
            --- a/README.md
            +++ b/README.md
            @@ -1 +1 @@
            -old
            +new
        """)
        diff_file = tmp_path / "doc.patch"
        diff_file.write_text(diff_content)

        with pytest.raises(ValueError, match="No supported file changes found"):
            run_pipeline_diff(str(diff_file))

    def test_only_deletions_diff_raises(self, tmp_path):
        from impactguard.pipeline import run_pipeline_diff

        diff_content = textwrap.dedent("""\
            --- a/module.py
            +++ /dev/null
            @@ -1,2 +0,0 @@
            -def gone():
            -    pass
        """)
        diff_file = tmp_path / "deleted.patch"
        diff_file.write_text(diff_content)

        with pytest.raises(ValueError, match="only deletions"):
            run_pipeline_diff(str(diff_file))

    def test_output_dir_is_respected(self, tmp_path):
        from impactguard.pipeline import run_pipeline_diff

        old_src = "def foo(): pass\n"
        new_src = "def foo(x=1): pass\n"
        diff_content = _make_unified_diff(old_src, new_src)
        diff_file = tmp_path / "changes.patch"
        diff_file.write_text(diff_content)

        out_dir = tmp_path / "output"
        out_dir.mkdir()

        result = run_pipeline_diff(str(diff_file), output_dir=str(out_dir))
        assert isinstance(result, dict)

    def test_pipeline_diff_exported_from_package(self):
        import impactguard

        assert hasattr(impactguard, "run_pipeline_diff")
        assert callable(impactguard.run_pipeline_diff)


# ---------------------------------------------------------------------------
# run_pipeline_commit
# ---------------------------------------------------------------------------

class TestRunPipelineCommit:
    def test_invalid_ref_raises(self):
        from impactguard.pipeline import run_pipeline_commit

        with pytest.raises(ValueError, match="Invalid git reference"):
            run_pipeline_commit("bad ref; rm -rf /")

    def test_valid_ref_with_no_parent_raises(self):
        from impactguard.pipeline import run_pipeline_commit

        err = subprocess.CalledProcessError(128, ["git", "rev-parse"])
        with mock.patch("subprocess.run", side_effect=err):
            with pytest.raises(ValueError, match="Cannot find parent commit"):
                run_pipeline_commit("HEAD")

    def test_timeout_raises(self):
        from impactguard.pipeline import run_pipeline_commit

        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 30)):
            with pytest.raises(RuntimeError, match="Timeout"):
                run_pipeline_commit("HEAD")

    def test_delegates_to_run_pipeline_git(self):
        from impactguard.pipeline import run_pipeline_commit

        mock_result = subprocess.CompletedProcess(
            args=["git", "rev-parse"],
            returncode=0,
            stdout="abc123\n",
            stderr="",
        )
        expected = {"comparison": {"breaking": [], "nonbreaking": []}}
        with mock.patch("subprocess.run", return_value=mock_result):
            with mock.patch(
                "impactguard.pipeline.run_pipeline_git", return_value=expected
            ) as mock_git:
                result = run_pipeline_commit("HEAD", runtime_path="/tmp/rt.json")
                mock_git.assert_called_once_with(
                    old_ref="abc123",
                    new_ref="HEAD",
                    files=None,
                    runtime_path="/tmp/rt.json",
                    output_path=None,
                    config=None,
                )
                assert result == expected

    def test_pipeline_commit_exported_from_package(self):
        import impactguard

        assert hasattr(impactguard, "run_pipeline_commit")
        assert callable(impactguard.run_pipeline_commit)


# ---------------------------------------------------------------------------
# CLI: check-diff
# ---------------------------------------------------------------------------

class TestCliCheckDiff:
    def test_check_diff_help(self):
        code = run_cli(["check-diff", "--help"])
        assert code == 0

    def test_check_diff_missing_file(self, tmp_path):
        code = run_cli(["check-diff", str(tmp_path / "does_not_exist.patch")])
        assert code == 1

    def test_check_diff_no_python_changes(self, tmp_path):
        diff_file = tmp_path / "doc.patch"
        diff_file.write_text(
            "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"
        )
        code = run_cli(["check-diff", str(diff_file)])
        assert code == 1

    def test_check_diff_nonbreaking_change(self, tmp_path):
        old_src = "def foo(x):\n    return x\n"
        new_src = "def foo(x, y=0):\n    return x\n"
        diff_content = _make_unified_diff(old_src, new_src)
        diff_file = tmp_path / "changes.patch"
        diff_file.write_text(diff_content)

        code = run_cli(["check-diff", str(diff_file)])
        # non-breaking → exit 0
        assert code == 0


# ---------------------------------------------------------------------------
# CLI: check-commit
# ---------------------------------------------------------------------------

class TestCliCheckCommit:
    def test_check_commit_help(self):
        code = run_cli(["check-commit", "--help"])
        assert code == 0

    def test_check_commit_invalid_ref(self):
        code = run_cli(["check-commit", "bad ref; evil"])
        assert code == 1

    def test_check_commit_no_git_repo(self, tmp_path, monkeypatch):
        # Simulate subprocess failure (no parent)
        monkeypatch.chdir(tmp_path)
        err = subprocess.CalledProcessError(128, ["git"])
        with mock.patch("subprocess.run", side_effect=err):
            code = run_cli(["check-commit", "HEAD"])
        assert code == 1


# ---------------------------------------------------------------------------
# run_pipeline_diff_content (new in-memory / pipe variant)
# ---------------------------------------------------------------------------

class TestRunPipelineDiffContent:
    def test_basic_change(self):
        from impactguard.pipeline import run_pipeline_diff_content

        old_src = "def foo(x):\n    return x\n"
        new_src = "def foo(x, y=0):\n    return x + y\n"
        diff_text = _make_unified_diff(old_src, new_src)

        result = run_pipeline_diff_content(diff_text)
        assert isinstance(result, dict)
        assert "comparison" in result or "signatures" in result

    def test_no_python_files_raises(self):
        from impactguard.pipeline import run_pipeline_diff_content

        diff_text = textwrap.dedent("""\
            --- a/README.md
            +++ b/README.md
            @@ -1 +1 @@
            -old
            +new
        """)
        with pytest.raises(ValueError, match="No supported file changes found"):
            run_pipeline_diff_content(diff_text)

    def test_only_deletions_raises(self):
        from impactguard.pipeline import run_pipeline_diff_content

        diff_text = textwrap.dedent("""\
            --- a/module.py
            +++ /dev/null
            @@ -1,2 +0,0 @@
            -def gone():
            -    pass
        """)
        with pytest.raises(ValueError, match="only deletions"):
            run_pipeline_diff_content(diff_text)

    def test_empty_diff_raises(self):
        from impactguard.pipeline import run_pipeline_diff_content

        with pytest.raises(ValueError, match="No supported file changes found"):
            run_pipeline_diff_content("")

    def test_output_dir_is_respected(self, tmp_path):
        from impactguard.pipeline import run_pipeline_diff_content

        old_src = "def foo(): pass\n"
        new_src = "def foo(x=1): pass\n"
        diff_text = _make_unified_diff(old_src, new_src)

        out_dir = tmp_path / "output"
        out_dir.mkdir()
        result = run_pipeline_diff_content(diff_text, output_dir=str(out_dir))
        assert isinstance(result, dict)

    def test_exported_from_package(self):
        import impactguard

        assert hasattr(impactguard, "run_pipeline_diff_content")
        assert callable(impactguard.run_pipeline_diff_content)

    def test_same_result_as_run_pipeline_diff(self, tmp_path):
        """run_pipeline_diff_content should produce the same output as run_pipeline_diff."""
        from impactguard.pipeline import run_pipeline_diff, run_pipeline_diff_content

        old_src = "def greet(name):\n    return name\n"
        new_src = "def greet(name, greeting='Hello'):\n    return greeting + name\n"
        diff_text = _make_unified_diff(old_src, new_src)
        diff_file = tmp_path / "changes.patch"
        diff_file.write_text(diff_text)

        result_file = run_pipeline_diff(str(diff_file))
        result_content = run_pipeline_diff_content(diff_text)

        # Both should agree on the comparison counts
        breaking_file = len(result_file.get("comparison", {}).get("breaking", []))
        breaking_content = len(result_content.get("comparison", {}).get("breaking", []))
        nonbreaking_file = len(result_file.get("comparison", {}).get("nonbreaking", []))
        nonbreaking_content = len(result_content.get("comparison", {}).get("nonbreaking", []))
        assert breaking_file == breaking_content
        assert nonbreaking_file == nonbreaking_content



# ---------------------------------------------------------------------------
# Multi-language diff support
# ---------------------------------------------------------------------------

class TestMultiLanguageDiff:
    """Verify that non-Python supported files in a diff are processed."""

    def test_mixed_diff_does_not_raise(self, tmp_path):
        """A diff touching Python + Makefile + C + README runs without error."""
        from impactguard.pipeline import run_pipeline_diff

        py_diff = _make_unified_diff(
            "def foo(x):\n    return x\n",
            "def foo(x, y=0):\n    return x + y\n",
            "module.py",
        )
        # Unsupported files appended — they should be silently skipped
        extra = textwrap.dedent("""\
            --- a/Makefile
            +++ b/Makefile
            @@ -1 +1 @@
            -build:
            +build: test
            --- a/lib.c
            +++ b/lib.c
            @@ -1,3 +1,3 @@
            -int add(int a, int b) {
            +int add(int a, int b, int c) {
                 return a + b;
             }
            --- a/README.md
            +++ b/README.md
            @@ -1 +1 @@
            -old
            +new
            --- a/index.html
            +++ b/index.html
            @@ -1 +1 @@
            -<p>old</p>
            +<p>new</p>
        """)
        diff_file = tmp_path / "mixed.patch"
        diff_file.write_text(py_diff + extra)

        result = run_pipeline_diff(str(diff_file))
        assert isinstance(result, dict)
        # The Python change should still be analysed
        assert "comparison" in result or "signatures" in result

    def test_only_unsupported_files_raises(self, tmp_path):
        """A diff with only Makefile/README raises ValueError."""
        from impactguard.pipeline import run_pipeline_diff

        diff_content = textwrap.dedent("""\
            --- a/Makefile
            +++ b/Makefile
            @@ -1 +1 @@
            -build:
            +build: test
            --- a/README.md
            +++ b/README.md
            @@ -1 +1 @@
            -old
            +new
        """)
        diff_file = tmp_path / "unsupported.patch"
        diff_file.write_text(diff_content)

        with pytest.raises(ValueError, match="No supported file changes found"):
            run_pipeline_diff(str(diff_file))

    def test_typescript_only_diff_does_not_raise(self, tmp_path):
        """A diff with only TypeScript changes runs without error."""
        from impactguard.pipeline import run_pipeline_diff

        ts_diff = textwrap.dedent("""\
            --- a/api.ts
            +++ b/api.ts
            @@ -1,3 +1,3 @@
            -function greet(name: string): string {
            +function greet(name: string, greeting: string = 'Hello'): string {
                 return name;
             }
        """)
        diff_file = tmp_path / "ts.patch"
        diff_file.write_text(ts_diff)

        result = run_pipeline_diff(str(diff_file))
        assert isinstance(result, dict)

    def test_extract_by_language_dispatches_correctly(self, tmp_path):
        """_extract_by_language groups files and calls the right extractor."""
        from impactguard.pipeline import _extract_by_language

        py_file = tmp_path / "mod.py"
        py_file.write_text("def foo(x):\n    return x\n")

        sigs = _extract_by_language([str(py_file)])
        assert len(sigs) == 1
        assert sigs[0]["name"] == "foo"

    def test_extract_by_language_skips_unsupported(self, tmp_path):
        """_extract_by_language silently skips files with no extractor."""
        from impactguard.pipeline import _extract_by_language

        md_file = tmp_path / "README.md"
        md_file.write_text("# title\n")
        make_file = tmp_path / "Makefile"
        make_file.write_text("build:\n\techo ok\n")

        sigs = _extract_by_language([str(md_file), str(make_file)])
        assert sigs == []


# ---------------------------------------------------------------------------
# CLI: check-diff --pipe
# ---------------------------------------------------------------------------

class TestCliCheckDiffPipe:
    def test_pipe_nonbreaking_change(self, monkeypatch):
        old_src = "def foo(x):\n    return x\n"
        new_src = "def foo(x, y=0):\n    return x\n"
        diff_text = _make_unified_diff(old_src, new_src)

        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(diff_text))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        code = run_cli(["check-diff", "--pipe"])
        assert code == 0

    def test_pipe_empty_diff_returns_error(self, monkeypatch):
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        code = run_cli(["check-diff", "--pipe"])
        assert code == 1

    def test_pipe_no_stdin_data_error(self, monkeypatch):
        """--pipe with a TTY (no piped data) should fail with an error."""
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        code = run_cli(["check-diff", "--pipe"])
        assert code == 1

    def test_pipe_no_python_files_error(self, monkeypatch):
        diff_text = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(diff_text))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        code = run_cli(["check-diff", "--pipe"])
        assert code == 1

    def test_check_diff_help_mentions_pipe(self, capsys):
        """--help for check-diff should mention --pipe."""
        run_cli(["check-diff", "--help"])
        # argparse prints to stdout; check captured output
        captured = capsys.readouterr()
        assert "--pipe" in captured.out

