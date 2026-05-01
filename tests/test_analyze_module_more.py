"""More tests for analyze_module module."""

import ast
from pathlib import Path
from impactguard.analyze_module import Analyzer, Scope


def test_analyzer_with_scope():
    """Test Analyzer with function scopes."""
    code = '''
def outer():
    x: int = 10

    def inner():
        return x
'''
    tree = ast.parse(code)
    analyzer = Analyzer("test.py")
    analyzer.visit(tree)

    # inner function should be analyzed
    assert len(analyzer.imports) == 0


def test_analyzer_type_annotations():
    """Test Analyzer with type annotations."""
    code = '''
def foo(x: int, y: str = "default") -> bool:
    return True

class MyClass:
    def method(self, items: list[int]) -> None:
        pass
'''
    tree = ast.parse(code)
    analyzer = Analyzer("test.py")
    analyzer.visit(tree)


def test_analyzer_with_decorators():
    """Test Analyzer with decorators."""
    code = '''
@decorator
def decorated():
    pass

@classmethod
def class_method(cls):
    pass
'''
    tree = ast.parse(code)
    analyzer = Analyzer("test.py")
    analyzer.visit(tree)


def test_analyzer_vararg():
    """Test Analyzer with *args and **kwargs."""
    code = '''
def func(*args, **kwargs):
    pass
'''
    tree = ast.parse(code)
    analyzer = Analyzer("test.py")
    analyzer.visit(tree)
