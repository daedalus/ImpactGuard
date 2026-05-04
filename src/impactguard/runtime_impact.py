"""Runtime impact analysis - wrapper around impact_analysis."""

import sys
from .impact_analysis import analyze, load_funcs, required_positional, total_positional

# Re-export for backwards compatibility
__all__ = ["analyze", "load_funcs", "required_positional", "total_positional"]
