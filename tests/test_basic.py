import tomllib
from pathlib import Path

import impactguard


def test_version():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert impactguard.__version__ == expected
