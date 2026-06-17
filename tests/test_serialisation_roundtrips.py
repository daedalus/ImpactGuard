"""Round-trip tests for cache serialisation in impactguard.cache.

Ensures _wrap_value → _unwrap_value preserves identity for every type
the cache actually stores.  Catches regressions like the ast.dump/
ast.parse round-trip bug (bce1023 → 76ddf8e) where the serialised
format was not valid input for the deserialiser.
"""

from __future__ import annotations

import ast
import json

import pytest

from impactguard.cache import _unwrap_value, _wrap_value


class TestJSONRoundTrips:
    """Values that serialise as JSON must survive the round-trip exactly."""

    @pytest.mark.parametrize(
        "value",
        [
            "hello",
            42,
            3.14,
            True,
            None,
            [1, 2, 3],
            {"a": 1, "b": [4, 5]},
            {"nested": {"deep": {"key": "val"}}},
        ],
        ids=lambda v: type(v).__name__,
    )
    def test_json_round_trip(self, value: object) -> None:
        wrapped = _wrap_value(value)
        restored = _unwrap_value(wrapped)
        assert restored == value

    def test_json_envelope_type(self) -> None:
        wrapped = _wrap_value({"foo": "bar"})
        parsed = json.loads(wrapped)
        assert parsed["_t"] == "json"


class TestASTRoundTrips:
    """AST trees must round-trip via ast.unparse / ast.parse, NOT ast.dump."""

    @pytest.mark.parametrize(
        "source",
        [
            "def foo(x: int) -> str: return str(x)",
            "class MyClass:\n    def method(self) -> None: ...",
            "import os\nfrom pathlib import Path",
            "x: int = 42",
            "async def coro() -> None: await something()",
            "match x:\n    case 1: pass\n    case _: pass",
            "def f(a, b=1, *args, kw=2, **kwargs): pass",
        ],
        ids=lambda s: s.split("\n")[0][:40],
    )
    def test_ast_round_trip(self, source: str) -> None:
        tree = ast.parse(source)
        wrapped = _wrap_value(tree)
        restored = _unwrap_value(wrapped)

        assert isinstance(restored, ast.Module)

        orig_names = sorted(
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        rest_names = sorted(
            n.name for n in ast.walk(restored)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        assert rest_names == orig_names

    def test_ast_envelope_type(self) -> None:
        tree = ast.parse("x = 1")
        wrapped = _wrap_value(tree)
        parsed = json.loads(wrapped)
        assert parsed["_t"] == "ast_dump"

    def test_ast_not_pickle(self) -> None:
        tree = ast.parse("def f(): pass")
        wrapped = _wrap_value(tree)
        parsed = json.loads(wrapped)
        assert parsed["_t"] != "pickle"


class TestPickleFallback:
    """Non-AST, non-JSON types still fall through to pickle."""

    def test_set_round_trip(self) -> None:
        value = {1, 2, 3}
        wrapped = _wrap_value(value)
        parsed = json.loads(wrapped)
        assert parsed["_t"] == "pickle"
        restored = _unwrap_value(wrapped)
        assert restored == value

    def test_bytes_round_trip(self) -> None:
        value = b"\x00\x01\x02"
        wrapped = _wrap_value(value)
        restored = _unwrap_value(wrapped)
        assert restored == value
