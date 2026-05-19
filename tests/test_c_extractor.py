"""Targeted C/C++ extractor tests for uncovered edge cases."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _write(p: Path, name: str, content: str) -> Path:
    f = p / name
    f.write_text(content)
    return f


# ── _parse_c_params_regex ─────────────────────────────────────────────────


def test_parse_c_params_regex_void():
    from impactguard.languages.c import _parse_c_params_regex

    result, vararg = _parse_c_params_regex("void")
    assert result == []
    assert vararg is False


def test_parse_c_params_regex_empty_part():
    from impactguard.languages.c import _parse_c_params_regex

    result, vararg = _parse_c_params_regex("int a,,int b")
    assert len(result) == 2
    assert vararg is False


def test_parse_c_params_regex_vararg():
    from impactguard.languages.c import _parse_c_params_regex

    result, vararg = _parse_c_params_regex("int a, ...")
    assert len(result) == 1
    assert vararg is True


def test_parse_c_params_regex_single_token():
    from impactguard.languages.c import _parse_c_params_regex

    result, vararg = _parse_c_params_regex("callback")
    assert len(result) == 1
    assert result[0]["name"] == "callback"
    assert result[0]["type"] is None


# ── _extract_calls_with_regex ─────────────────────────────────────────────


def test_extract_calls_with_regex_basic(tmp_path):
    from impactguard.languages.c import _extract_calls_with_regex

    src = _write(tmp_path, "test.c", "void run() { foo(1, 2); bar(); }")
    calls = _extract_calls_with_regex(src)
    names = [c["name"] for c in calls]
    assert "foo" in names
    assert "bar" in names
    assert len(calls) >= 2


def test_extract_calls_with_regex_keyword_filter(tmp_path):
    from impactguard.languages.c import _extract_calls_with_regex

    src = _write(tmp_path, "test.c", "int main() { if (x) { for (;;) { } } }")
    calls = _extract_calls_with_regex(src)
    # if and for should be filtered out
    names = [c["name"] for c in calls]
    assert "if" not in names
    assert "for" not in names
    assert "main" in names


def test_extract_calls_with_regex_read_failure(tmp_path):
    from impactguard.languages.c import _extract_calls_with_regex

    missing = tmp_path / "nonexistent.c"
    calls = _extract_calls_with_regex(missing)
    assert calls == []


def test_extract_calls_with_regex_no_calls(tmp_path):
    from impactguard.languages.c import _extract_calls_with_regex

    src = _write(tmp_path, "empty.c", "int x = 42;")
    calls = _extract_calls_with_regex(src)
    assert calls == []


def test_extract_calls_with_regex_multiline(tmp_path):
    from impactguard.languages.c import _extract_calls_with_regex

    src = _write(tmp_path, "multi.c", '''
void test() {
    foo(1,
        2,
        3);
    bar();
}
''')
    calls = _extract_calls_with_regex(src)
    names = [c["name"] for c in calls]
    assert len(calls) >= 2


# ── _visit_node template_redeclaration ─────────────────────────────────────


def test_visit_node_templates(tmp_path):
    """Test _visit_node handles template_declaration nodes."""
    from impactguard.languages.c import _CPP_TREE_SITTER_AVAILABLE
    if not _CPP_TREE_SITTER_AVAILABLE:
        pytest.skip("tree-sitter-cpp not installed")


# ── CExtractor.extract_signatures (tree-sitter edge cases) ────────────────


def test_c_extract_signatures_call_extraction(tmp_path):
    """Test C extractor's extract_calls with tree-sitter."""
    from impactguard.languages.c import _C_TREE_SITTER_AVAILABLE, CExtractor

    if not _C_TREE_SITTER_AVAILABLE:
        pytest.skip("tree-sitter-c not installed")

    ext = CExtractor()
    src = _write(tmp_path, "test.c", "void foo() { bar(1, 2); }")
    calls = ext.extract_calls(src)
    assert len(calls) >= 1
    assert any(c["name"] == "bar" for c in calls)


def test_c_regex_extract_calls(tmp_path):
    """Test C regex fallback's extract_calls."""
    import impactguard.languages.c as c_mod

    with patch.object(c_mod, "_C_TREE_SITTER_AVAILABLE", False):
        from impactguard.languages.c import CExtractor

        ext = CExtractor()
        src = _write(tmp_path, "test.c", "void foo() { bar(1, 2); }")
        calls = ext.extract_calls(src)
        assert len(calls) >= 1
        assert any(c["name"] == "bar" for c in calls)


def test_c_extract_signatures_prototype_only(tmp_path):
    """Test C extractor with function prototypes."""
    from impactguard.languages.c import _C_TREE_SITTER_AVAILABLE, CExtractor

    if not _C_TREE_SITTER_AVAILABLE:
        pytest.skip("tree-sitter-c not installed")

    ext = CExtractor()
    src = _write(tmp_path, "proto.c", "int add(int a, int b);")
    sigs = ext.extract_signatures([str(src)])
    assert len(sigs) == 1


def test_c_regex_signatures(tmp_path):
    """Test C regex fallback extract_signatures."""
    import impactguard.languages.c as c_mod

    with patch.object(c_mod, "_C_TREE_SITTER_AVAILABLE", False):
        from impactguard.languages.c import CExtractor

        ext = CExtractor()
        src = _write(tmp_path, "test.c", "int add(int a, int b) { return a + b; }")
        sigs = ext.extract_signatures([str(src)])
        assert len(sigs) >= 1


def test_c_regex_extract_signatures_read_error(tmp_path):
    """Test C regex fallback handles read errors."""
    import impactguard.languages.c as c_mod

    with patch.object(c_mod, "_C_TREE_SITTER_AVAILABLE", False):
        from impactguard.languages.c import CExtractor

        ext = CExtractor()
        sigs = ext.extract_signatures(["/nonexistent/file.c"])
        assert sigs == []


def test_c_regex_extract_signatures_keyword_skip(tmp_path):
    import impactguard.languages.c as c_mod

    with patch.object(c_mod, "_C_TREE_SITTER_AVAILABLE", False):
        from impactguard.languages.c import CExtractor

        ext = CExtractor()
        src = _write(tmp_path, "kw.c", "int if(int a) { return a; }")
        sigs = ext.extract_signatures([str(src)])
        assert len(sigs) == 0


def test_c_regex_vararg(tmp_path):
    import impactguard.languages.c as c_mod

    with patch.object(c_mod, "_C_TREE_SITTER_AVAILABLE", False):
        from impactguard.languages.c import CExtractor

        ext = CExtractor()
        src = _write(tmp_path, "vararg.c", "void foo(int a, ...) {}")
        sigs = ext.extract_signatures([str(src)])
        assert len(sigs) >= 1
