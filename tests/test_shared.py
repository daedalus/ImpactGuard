"""Tests for shared.py covering tree-sitter edge cases."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_node(type_: str, **kwargs) -> MagicMock:
    """Helper to create a mock tree-sitter Node."""
    node = MagicMock()
    node.type = type_
    for k, v in kwargs.items():
        setattr(node, k, v)
    return node


# ── make_parser ────────────────────────────────────────────────────────────


def test_make_parser_not_available():
    from impactguard.languages.lib.shared import make_parser

    with patch("impactguard.languages.lib.shared._TREE_SITTER_AVAILABLE", False):
        result = make_parser("test", MagicMock())
        assert result is None


def test_make_parser_exception():
    from impactguard.languages.lib.shared import make_parser

    bad_lang = MagicMock(side_effect=RuntimeError("parser creation failed"))
    with patch("impactguard.languages.lib.shared._TreeSitterParser", bad_lang):
        result = make_parser("test", MagicMock())
        assert result is None


def test_make_parser_success():
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_c")
    from tree_sitter import Language as TSLanguage
    from tree_sitter_c import language as c_language

    from impactguard.languages.lib.shared import make_parser

    ts_c = TSLanguage(c_language())
    result = make_parser("c", ts_c)
    assert result is not None


# ── _extract_call_name ─────────────────────────────────────────────────────


def test_extract_call_name_identifier():
    from impactguard.languages.lib.shared import _extract_call_name

    node = _make_node("identifier", start_byte=0, end_byte=3)
    result = _extract_call_name(node, b"foo()")
    assert result == "foo"


def test_extract_call_name_member_map_none():
    from impactguard.languages.lib.shared import _extract_call_name

    child_a = _make_node("prop_a", start_byte=0, end_byte=1)
    child_b = _make_node("prop_b", start_byte=1, end_byte=2)
    node = _make_node("member_expression", named_children=[child_a, child_b])

    result = _extract_call_name(node, b"ab", member_map={"member_expression": None})
    assert result == "a.b"


def test_extract_call_name_member_map_with_field():
    from impactguard.languages.lib.shared import _extract_call_name

    child = _make_node("field_identifier", start_byte=2, end_byte=5)
    parent = _make_node(
        "member_expression",
        named_children=[_make_node("ignored", start_byte=0, end_byte=1), child],
    )

    result = _extract_call_name(
        parent, b"x.foo", member_map={"member_expression": "field_identifier"}
    )
    assert result == "foo"


def test_extract_call_name_member_map_field_missing():
    from impactguard.languages.lib.shared import _extract_call_name

    parent = _make_node(
        "member_expression",
        named_children=[_make_node("other", start_byte=0, end_byte=1)],
    )

    result = _extract_call_name(
        parent, b"ab", member_map={"member_expression": "field_identifier"}
    )
    assert result is None


def test_extract_call_name_unknown_no_children():
    from impactguard.languages.lib.shared import _extract_call_name

    node = _make_node("unknown", named_children=[])
    result = _extract_call_name(node, b"ab")
    assert result is None


def test_extract_call_name_recursive():
    from impactguard.languages.lib.shared import _extract_call_name

    inner = _make_node("identifier", start_byte=0, end_byte=3)
    outer = _make_node("wrapper", named_children=[inner])

    result = _extract_call_name(outer, b"foo()")
    assert result == "foo"


# ── _resolve_call_name_from_node ──────────────────────────────────────────


def test_resolve_call_name_name_on_call():
    from impactguard.languages.lib.shared import _resolve_call_name_from_node

    name_child = _make_node("identifier", start_byte=0, end_byte=3)
    node = _make_node("call", child_by_field_name=MagicMock(return_value=name_child))

    result = _resolve_call_name_from_node(
        node,
        b"foo()",
        name_on_call=True,
        fallback_ident=True,
        member_map=None,
        ident_type=None,
        first_ident=MagicMock(return_value="bar"),
    )
    assert result == "foo"


def test_resolve_call_name_fallback_ident():
    from impactguard.languages.lib.shared import _resolve_call_name_from_node

    node = _make_node("call", child_by_field_name=MagicMock(return_value=None))

    result = _resolve_call_name_from_node(
        node,
        b"foo()",
        name_on_call=True,
        fallback_ident=True,
        member_map=None,
        ident_type=None,
        first_ident=MagicMock(return_value="fallback_name"),
    )
    assert result == "fallback_name"


def test_resolve_call_name_no_fallback_and_no_name():
    from impactguard.languages.lib.shared import _resolve_call_name_from_node

    node = _make_node("call", child_by_field_name=MagicMock(return_value=None))

    result = _resolve_call_name_from_node(
        node,
        b"foo()",
        name_on_call=True,
        fallback_ident=False,
        member_map=None,
        ident_type=None,
        first_ident=MagicMock(),
    )
    assert result is None


def test_resolve_call_name_func_node_from_named_children():
    from impactguard.languages.lib.shared import _resolve_call_name_from_node

    inner = _make_node("identifier", start_byte=0, end_byte=3)
    node = _make_node(
        "call",
        child_by_field_name=MagicMock(
            side_effect=lambda f: None if f == "function" else None
        ),
        named_children=[inner],
    )

    result = _resolve_call_name_from_node(
        node,
        b"foo()",
        name_on_call=False,
        fallback_ident=False,
        member_map=None,
        ident_type=None,
        first_ident=MagicMock(),
    )
    assert result == "foo"


def test_resolve_call_name_no_func_node():
    from impactguard.languages.lib.shared import _resolve_call_name_from_node

    node = _make_node(
        "call", child_by_field_name=MagicMock(return_value=None), named_children=[]
    )

    result = _resolve_call_name_from_node(
        node,
        b"foo()",
        name_on_call=False,
        fallback_ident=False,
        member_map=None,
        ident_type=None,
        first_ident=MagicMock(),
    )
    assert result is None


# ── _resolve_args_node ────────────────────────────────────────────────────


def test_resolve_args_node_with_arguments_field():
    from impactguard.languages.lib.shared import _resolve_args_node

    args_node = _make_node("args")
    node = _make_node("call", child_by_field_name=MagicMock(return_value=args_node))

    result = _resolve_args_node(node, "argument_list")
    assert result == args_node


def test_resolve_args_node_no_arguments_field():
    from impactguard.languages.lib.shared import _resolve_args_node

    node = _make_node(
        "call",
        child_by_field_name=MagicMock(return_value=None),
        named_children=[_make_node("argument_list")],
    )

    result = _resolve_args_node(node, "argument_list")
    assert result is not None
    assert result.type == "argument_list"


def test_resolve_args_node_fallback_last_child():
    from impactguard.languages.lib.shared import _resolve_args_node

    child = _make_node("last_child")
    node = _make_node(
        "call",
        child_by_field_name=MagicMock(return_value=None),
        named_children=[_make_node("a"), child],
    )

    result = _resolve_args_node(node, "argument_list")
    assert result == child


def test_resolve_args_node_no_children():
    from impactguard.languages.lib.shared import _resolve_args_node

    node = _make_node(
        "call", child_by_field_name=MagicMock(return_value=None), named_children=[]
    )

    result = _resolve_args_node(node, "argument_list")
    assert result is None


# ── _count_call_args ──────────────────────────────────────────────────────


def test_count_call_args_arithmetic():
    from impactguard.languages.lib.shared import _count_call_args

    node = _make_node("call", named_children=[1, 2, 3])

    result = _count_call_args(
        node, count_args="arithmetic", count_types=None, args_type="args"
    )
    assert result == 2


def test_count_call_args_no_args():
    from impactguard.languages.lib.shared import _count_call_args

    node = _make_node(
        "call", child_by_field_name=MagicMock(return_value=None), named_children=[]
    )

    result = _count_call_args(
        node, count_args="named", count_types=None, args_type="args"
    )
    assert result == 0


def test_count_call_args_include_with_types():
    from impactguard.languages.lib.shared import _count_call_args

    arg_node = _make_node("args", children=[_make_node("arg_a"), _make_node("arg_b")])
    node = _make_node("call", child_by_field_name=MagicMock(return_value=arg_node))

    result = _count_call_args(
        node, count_args="include", count_types={"arg_a"}, args_type="args"
    )
    assert result == 1


def test_count_call_args_include_no_types():
    from impactguard.languages.lib.shared import _count_call_args

    arg_node = _make_node("args", children=[_make_node("a"), _make_node("b")])
    node = _make_node("call", child_by_field_name=MagicMock(return_value=arg_node))

    result = _count_call_args(
        node, count_args="include", count_types=set(), args_type="args"
    )
    assert result == 0


# ── extract_calls_with_tree_sitter ────────────────────────────────────────


def test_extract_calls_not_available():
    from impactguard.languages.lib.shared import extract_calls_with_tree_sitter

    with patch("impactguard.languages.lib.shared._TREE_SITTER_AVAILABLE", False):
        result = extract_calls_with_tree_sitter(Path("/x"), "test", MagicMock())
        assert result == []


def test_extract_calls_no_parser():
    from impactguard.languages.lib.shared import extract_calls_with_tree_sitter

    with patch("impactguard.languages.lib.shared._TREE_SITTER_AVAILABLE", True):
        with patch("impactguard.languages.lib.shared.make_parser", return_value=None):
            result = extract_calls_with_tree_sitter(Path("/x"), "test", MagicMock())
            assert result == []


def test_extract_calls_read_error(tmp_path):
    from impactguard.languages.lib.shared import extract_calls_with_tree_sitter

    missing = tmp_path / "nonexistent.txt"

    with patch("impactguard.languages.lib.shared._TREE_SITTER_AVAILABLE", True):
        result = extract_calls_with_tree_sitter(missing, "test", MagicMock())
        assert result == []


def test_extract_calls_with_real_c_parser(tmp_path):
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_c")
    from tree_sitter import Language as TSLanguage
    from tree_sitter_c import language as c_language

    from impactguard.languages.lib.shared import extract_calls_with_tree_sitter

    src = tmp_path / "test.c"
    src.write_text("void foo() { bar(); }")

    result = extract_calls_with_tree_sitter(
        src,
        "c",
        TSLanguage(c_language()),
        call_type="call_expression",
    )
    assert len(result) >= 1
    assert result[0]["name"] == "bar"


# ── _first_ident ──────────────────────────────────────────────────────────


def test_extract_calls_with_first_ident_fallback(tmp_path):
    from impactguard.languages.lib.shared import extract_calls_with_tree_sitter

    with patch("impactguard.languages.lib.shared._TREE_SITTER_AVAILABLE", True):
        with patch("impactguard.languages.lib.shared.make_parser", return_value=None):
            result = extract_calls_with_tree_sitter(
                Path("/nonexistent"), "test", MagicMock()
            )
            assert result == []


# ── register_extractor ────────────────────────────────────────────────────


def test_register_extractor():
    from impactguard.languages.lib.shared import register_extractor

    with patch("impactguard.languages.lib.registry.register") as mock_reg:
        instance = MagicMock()
        register_extractor(instance)
        mock_reg.assert_called_once_with(instance)


# ── warn_if_no_tree_sitter ────────────────────────────────────────────────


def test_warn_if_no_tree_sitter_already_warned():
    from impactguard.languages.lib.shared import warn_if_no_tree_sitter

    obj = MagicMock()
    obj._warned = True

    with patch("warnings.warn") as mock_warn:
        warn_if_no_tree_sitter(obj, "TestLang", "tree-sitter-test")
        mock_warn.assert_not_called()


def test_warn_if_no_tree_sitter_first_time():
    from impactguard.languages.lib.shared import warn_if_no_tree_sitter

    with patch("warnings.warn") as mock_warn:
        obj = MagicMock()
        obj._warned = False
        warn_if_no_tree_sitter(obj, "TestLang", "tree-sitter-test")
        mock_warn.assert_called_once()
        assert obj._warned is True
