"""Simple test to verify imports work."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_import():
    """Test that impactguard can be imported."""
    import impactguard

    assert impactguard.__version__ == "0.1.4"


def test_extract():
    """Test extract function."""
    from impactguard import extract

    result = extract([])
    assert isinstance(result, list)
