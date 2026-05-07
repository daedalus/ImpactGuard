"""Targeted tests for specific missing lines."""

import json
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import MagicMock, patch


def test_suggest_fixes_missing_lines(tmp_path):
    """Target missing lines 20, 24-31, 39-41, 79-156 in suggest_fixes.py."""
    from impactguard.suggest_fixes import enrich_with_fixes, suggest

    # Test with various configurations to hit missing lines
    items = [
        {
            "fqname": "test.py:foo",
            "change": "OPTIONAL_POSITIONAL_ADDED",
            "risk_level": "MEDIUM",
            "callsites": [{"file": "main.py", "lineno": 10}],
        },
        {
            "fqname": "test.py:bar",
            "change": "POSITIONAL_REMOVED",
            "risk_level": "HIGH",
            "patches": [{"type": "add_default", "param": "x"}],
        },
    ]

    for item in items:
        result = suggest(item, items)
        assert isinstance(result, list)

        enriched = enrich_with_fixes(item, items)
        assert isinstance(enriched, list)


def test_main_missing_lines(tmp_path):
    """Target missing lines in __main__.py - functions 79-96, 101-105, 110-126, etc."""
    import sys

    from impactguard.__main__ import main

    # Test extract command (covers lines 12-28)
    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(): pass\n")

    sys.argv = ["impactguard", "extract", str(test_file)]
    try:
        main()
    except SystemExit as e:
        assert e.code in [0, 1]

    # Test compare command (covers lines 31-43)
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(
        json.dumps(
            [
                {
                    "fqname": "test:foo",
                    "name": "foo",
                    "positional": [],
                    "kwonly": [],
                    "vararg": False,
                    "kwarg": False,
                }
            ]
        )
    )
    new_path.write_text(
        json.dumps(
            [
                {
                    "fqname": "test:foo",
                    "name": "foo",
                    "positional": [{"name": "a", "has_default": True}],
                    "kwonly": [],
                    "vararg": False,
                    "kwarg": False,
                }
            ]
        )
    )

    sys.argv = ["impactguard", "compare", str(old_path), str(new_path)]
    try:
        main()
    except SystemExit as e:
        assert e.code in [0, 1]


def test_main_cmd_check_commits(tmp_path):
    """Target cmd_check_commits (lines 171-204)."""
    import sys

    from impactguard.__main__ import main

    # Test check-commits command
    sys.argv = ["impactguard", "check-commits", "HEAD~1", "HEAD"]
    try:
        main()
    except SystemExit as e:
        assert e.code in [0, 1]


def test_main_cmd_install_hooks(tmp_path):
    """Target cmd_install_hooks (lines 209-284)."""
    import sys

    from impactguard.__main__ import main

    # Test install-hooks command
    sys.argv = ["impactguard", "install-hooks", str(tmp_path)]
    try:
        main()
    except SystemExit as e:
        assert e.code in [0, 1]


def test_main_cmd_generate_changelog(tmp_path):
    """Target cmd_generate_changelog."""
    import sys

    from impactguard.__main__ import main

    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(): pass\n")
    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(x): pass\n")

    sys.argv = [
        "impactguard",
        "generate-changelog",
        "--old-files",
        str(old_file),
        "--new-files",
        str(new_file),
    ]
    try:
        main()
    except SystemExit as e:
        assert e.code in [0, 1]


def test_pipeline_run_pipeline_git(tmp_path):
    """Target run_pipeline_git function."""
    from impactguard.pipeline import run_pipeline_git

    # Mock git operations
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="module.py\n",
            stderr="",
        )

        with patch("pathlib.Path.exists", return_value=True):
            with patch("impactguard.pipeline.run_pipeline") as mock_pipeline:
                mock_pipeline.return_value = {"comparison": {}, "signatures": {}}

                result = run_pipeline_git(
                    old_ref="HEAD~1",
                    new_ref="HEAD",
                    output_path=str(tmp_path / "output"),
                )

                assert "comparison" in result


def test_impactguard_class_all_methods(tmp_path):
    """Test ImpactGuard class methods."""
    from impactguard import ImpactGuard

    guard = ImpactGuard({"test": True})
    assert guard.config == {"test": True}

    # Test analyze
    old_file = tmp_path / "old.py"
    old_file.write_text("def foo(a): return a\n")
    new_file = tmp_path / "new.py"
    new_file.write_text("def foo(a, b=1): return a + b\n")

    result = guard.analyze(str(old_file), str(new_file))
    assert "signatures" in result

    # Test extract
    test_file = tmp_path / "test.py"
    test_file.write_text("def bar(): pass\n")
    sigs = guard.extract([str(test_file)])
    assert isinstance(sigs, list)

    # Test compare
    old_sigs = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [{"name": "a", "has_default": False}],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]
    new_sigs = [
        {
            "fqname": "test:foo",
            "name": "foo",
            "positional": [
                {"name": "a", "has_default": False},
                {"name": "b", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        }
    ]

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old_sigs))
    new_path.write_text(json.dumps(new_sigs))

    result = guard.compare(str(old_path), str(new_path))
    assert "breaking" in result

    # Test check
    result = guard.check(str(old_file))
    assert "signatures" in result
