from typing import Any

"""
ImpactGuard CLI - Command-line interface for the ImpactGuard library.
"""

import argparse
import json
import sys


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract function signatures from Python files."""
    from .extract_signatures import extract

    files = (
        args.files
        if args.files
        else [f for f in sys.stdin.read().splitlines() if f.strip()]
    )

    if not files:
        print("Error: No input files provided", file=sys.stderr)
        return 1

    result = extract(files)
    print(json.dumps(result, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare two signature snapshots."""
    from .compare_signatures import compare

    result = compare(args.old, args.new)
    print(f"Breaking changes: {len(result['breaking'])}")
    print(f"Non-breaking changes: {len(result['nonbreaking'])}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)

    return 1 if result["breaking"] else 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Analyze impact of signature changes on call sites."""
    from .impact_analysis import analyze

    result = analyze(args.signatures, args.calls, args.runtime)
    print(json.dumps(result, indent=2))
    return 0


def cmd_risk(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Run risk analysis pipeline."""
    from .risk_gate import main as risk_main

    return risk_main(args.diff, args.runtime, args.output)


def cmd_report(args: argparse.Namespace) -> int:
    """Generate HTML report from risk JSON."""
    from .generate_report import main as report_main

    report_main(args.report, args.output)
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """Runtime tracing commands."""
    if args.trace_cmd == "install":
        import importlib

        from .trace_calls import install_tracer

        module = importlib.import_module(args.module)
        prefix = args.prefix
        install_tracer(module, prefix)
        print(f"Tracer installed for {args.module}")
        return 0

    elif args.trace_cmd == "dump":
        from .trace_calls import dump

        dump(args.output)
        print(f"Runtime data dumped to {args.output}")
        return 0

    return 1


def cmd_check(args: argparse.Namespace) -> int:
    """Run full ImpactGuard pipeline check."""
    from .pipeline import quick_check

    print(f"Checking impact: {args.old} → {args.new}")

    try:
        result = quick_check(args.old, args.new, args.runtime)
        print(f"\n=== Comparison ===")
        print(f"Breaking changes: {len(result.get('comparison', {}).get('breaking', []))}")
        print(f"Non-breaking changes: {len(result.get('comparison', {}).get('nonbreaking', []))}")

        if 'risk' in result:
            risk_items = result['risk']
            high = sum(1 for r in risk_items if r.get('risk') == 'HIGH')
            print(f"\n=== Risk Analysis ===")
            print(f"HIGH risk: {high}")

        if 'report_html' in result:
            output = args.output or 'impact_report.html'
            with open(output, 'w') as f:
                f.write(result['report_html'])
            print(f"\nReport written to {output}")

        if 'fixes' in result:
            fixes = result['fixes']
            if fixes:
                print(f"\n=== Suggested Fixes ({len(fixes)}) ===")
                for fix in fixes[:5]:
                    print(f"  - {fix}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_check_commits(args: argparse.Namespace) -> int:
    """Run ImpactGuard pipeline comparing two git commits."""
    from .pipeline import run_pipeline_git

    print(f"Checking impact: {args.old_ref} → {args.new_ref}")

    try:
        result = run_pipeline_git(
            old_ref=args.old_ref,
            new_ref=args.new_ref,
            runtime_path=args.runtime,
            output_path=args.output,
        )

        print(f"\n=== Comparison ===")
        comparison = result.get('comparison', {})
        print(f"Breaking changes: {len(comparison.get('breaking', []))}")
        print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")

        if 'risk' in result:
            risk_items = result['risk']
            high = sum(1 for r in risk_items if r.get('risk') == 'HIGH')
            print(f"\n=== Risk Analysis ===")
            print(f"HIGH risk: {high}")

        if 'report_html' in result and args.output:
            print(f"\nReport written to {args.output}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="impactguard",
        description="ImpactGuard - API impact analyzer for Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.0")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # extract subcommand
    extract_parser = subparsers.add_parser(
        "extract", help="Extract function signatures"
    )
    extract_parser.add_argument("files", nargs="*", help="Python files to analyze")
    extract_parser.set_defaults(func=cmd_extract)

    # compare subcommand
    compare_parser = subparsers.add_parser(
        "compare", help="Compare signature snapshots"
    )
    compare_parser.add_argument("old", help="Old signatures JSON file")
    compare_parser.add_argument("new", help="New signatures JSON file")
    compare_parser.add_argument("-o", "--output", help="Output file for results")
    compare_parser.set_defaults(func=cmd_compare)

    # analyze subcommand
    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze impact on call sites"
    )
    analyze_parser.add_argument("signatures", help="Signatures JSON file")
    analyze_parser.add_argument("calls", help="Call sites JSON file")
    analyze_parser.add_argument("runtime", nargs="?", help="Runtime data JSON file")
    analyze_parser.set_defaults(func=cmd_analyze)

    # risk subcommand
    risk_parser = subparsers.add_parser("risk", help="Run risk analysis")
    risk_parser.add_argument("diff", help="Diff text file")
    risk_parser.add_argument("runtime", help="Runtime data JSON file")
    risk_parser.add_argument("output", help="Output report JSON file")
    risk_parser.set_defaults(func=cmd_risk)

    # report subcommand
    report_parser = subparsers.add_parser("report", help="Generate HTML report")
    report_parser.add_argument("report", help="Risk report JSON file")
    report_parser.add_argument(
        "output", nargs="?", default="api_report.html", help="Output HTML file"
    )
    report_parser.set_defaults(func=cmd_report)

    # trace subcommand
    trace_parser = subparsers.add_parser("trace", help="Runtime tracing")
    trace_sub = trace_parser.add_subparsers(dest="trace_cmd", help="Trace commands")
    trace_install = trace_sub.add_parser("install", help="Install tracer")
    trace_install.add_argument("module", help="Module to trace")
    trace_install.add_argument("--prefix", help="Module prefix filter")
    trace_dump = trace_sub.add_parser("dump", help="Dump trace data")
    trace_dump.add_argument(
        "output", nargs="?", default=".runtime_calls.json", help="Output file"
    )
    trace_parser.set_defaults(func=cmd_trace)

    # check subcommand (NEW - integration)
    check_parser = subparsers.add_parser("check", help="Run full ImpactGuard pipeline check")
    check_parser.add_argument("old", help="Old Python file/directory")
    check_parser.add_argument("new", help="New Python file/directory")
    check_parser.add_argument("runtime", nargs="?", help="Runtime data JSON (optional)")
    check_parser.add_argument("output", nargs="?", default="impact_report.html", help="Output HTML report")
    check_parser.set_defaults(func=cmd_check)

    # check-commits subcommand (NEW - git commit comparison)
    check_commits_parser = subparsers.add_parser("check-commits", help="Compare two git commits")
    check_commits_parser.add_argument("old_ref", help="Old git reference (commit, branch, tag)")
    check_commits_parser.add_argument("new_ref", help="New git reference (commit, branch, tag)")
    check_commits_parser.add_argument("runtime", nargs="?", help="Runtime data JSON (optional)")
    check_commits_parser.add_argument("output", nargs="?", help="Output HTML report")
    check_commits_parser.set_defaults(func=cmd_check_commits)

    # Make 'check' the default if no subcommand provided but args look like paths
    if len(sys.argv) > 1 and sys.argv[1] not in [
        "extract", "compare", "analyze", "risk", "report", "trace", "check", "check-commits"
    ]:
        # Assume pipeline mode: impactguard old/ new/ [runtime] [output]
        sys.argv.insert(1, "check")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if hasattr(args, "func"):
        result: int = args.func(args)
        return result
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
