"""Shared test fixtures for ImpactGuard tests."""

import json
import tempfile

import pytest


@pytest.fixture
def sample_signature_data():
    """Provide sample signature data for tests."""
    return [
        {
            "fqname": "src/module.py:func_one",
            "name": "func_one",
            "file": "src/module.py",
            "lineno": 10,
            "end_lineno": 15,
            "positional": [
                {"name": "arg1", "has_default": False},
                {"name": "arg2", "has_default": True},
            ],
            "kwonly": [],
            "vararg": False,
            "kwarg": False,
        },
        {
            "fqname": "src/module.py:func_two",
            "name": "func_two",
            "file": "src/module.py",
            "lineno": 20,
            "end_lineno": 25,
            "positional": [],
            "kwonly": [],
            "vararg": True,
            "kwarg": False,
        },
    ]


@pytest.fixture
def sample_signatures_file(sample_signature_data):
    """Create a temporary signatures JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample_signature_data, f)
        return f.name


@pytest.fixture
def sample_python_file():
    """Create a temporary Python file with functions."""
    content = '''
def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"

async def async_func(data: list) -> dict:
    """Process data asynchronously."""
    return {"result": data}

class MyClass:
    def method(self, x: int) -> int:
        return x * 2
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def empty_python_file():
    """Create an empty Python file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("# Empty file\n")
        return f.name


@pytest.fixture
def runtime_data():
    """Provide sample runtime data."""
    return [
        {"function": "src/module.py:func_one", "count": 42},
        {"function": "src/module.py:func_two", "count": 10},
    ]


@pytest.fixture
def runtime_data_file(runtime_data):
    """Create a temporary runtime data JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(runtime_data, f)
        return f.name
