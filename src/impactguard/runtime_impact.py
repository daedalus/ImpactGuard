"""Runtime impact analysis - wrapper around impact_analysis."""

import sys
from .impact_analysis import analyze, load_funcs, required_positional, total_positional

# Re-export for backwards compatibility
__all__ = ["analyze", "load_funcs", "required_positional", "total_positional"]

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python runtime_impact.py <signatures.json> <calls.json>")
        sys.exit(1)

    issues = analyze(sys.argv[1], sys.argv[2])

    print("=== RUNTIME BREAKAGES ===")
    if issues:
        for issue in issues:
            print(f"{issue['function']} → {issue['change']} (count: {issue.get('count', '?')})")
        sys.exit(1)
    else:
        print("None")
        sys.exit(0)
