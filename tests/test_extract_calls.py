"""Tests for extract_calls module."""

import ast
import tempfile
from pathlib import Path

from impactguard.extract_calls import extract


def test_extract():
    """Test extract function."""
    code = '''
def foo():
    bar()
    baz(1, 2)
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        fname = f.name

    result = extract(Path(fname))
    assert len(result) == 2
    assert any(c["name"] == "bar" for c in result)
    assert any(c["name"] == "baz" for c in result)

    import os
    os.unlink(fname)
