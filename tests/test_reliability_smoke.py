"""Small deterministic smoke suite for CI reliability checks."""

import difflib
import io
import sys


def _run_cli(args: list[str], stdin_text: str | None = None) -> int:
    from impactguard.__main__ import main as cli_main

    old_argv = sys.argv[:]
    old_stdin = sys.stdin
    sys.argv = ["impactguard"] + args
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
        setattr(sys.stdin, "isatty", lambda: False)
    try:
        return cli_main() or 0
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = old_argv
        sys.stdin = old_stdin


def _make_diff(old_src: str, new_src: str, filename: str = "module.py") -> str:
    return "".join(
        difflib.unified_diff(
            old_src.splitlines(keepends=True),
            new_src.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )


def test_smoke_cli_version():
    assert _run_cli(["--version"]) == 0


def test_smoke_cli_extract(tmp_path):
    src = tmp_path / "demo.py"
    src.write_text("def add(a, b=1):\n    return a + b\n")
    assert _run_cli(["extract", str(src)]) == 0


def test_smoke_cli_check_diff_pipe_nonbreaking():
    diff_text = _make_diff(
        "def f(x):\n    return x\n",
        "def f(x, y=0):\n    return x + y\n",
    )
    assert _run_cli(["check-diff", "--pipe"], stdin_text=diff_text) == 0
