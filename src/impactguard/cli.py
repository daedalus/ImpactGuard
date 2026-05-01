"""
ImpactGuard CLI - Command-line interface for the ImpactGuard library.
"""

import argparse
import json
import sys


def cmd_extract(args):
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


def cmd_compare(args):
    """Compare two signature snapshots."""
    from .compare_signatures import compare

    result = compare(args.old, args.new)
    print(f"Breaking changes: {len(result['breaking'])}")
    print(f"Non-breaking changes: {len(result['nonbreaking'])}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)

    return 1 if result["breaking"] else 0


def cmd_analyze(args):
    """Analyze impact of signature changes on call sites."""
    from .impact_analysis import analyze

    result = analyze(args.signatures, args.calls, args.runtime)
    print(json.dumps(result, indent=2))
    return 0


def cmd_risk(args):
    """Run risk analysis pipeline."""
    from .risk_gate import main as risk_main

    return risk_main(args.diff, args.runtime, args.output)


def cmd_report(args):
    """Generate HTML report from risk JSON."""
    from .generate_report import main as report_main

    return report_main(args.report, args.output)


def cmd_trace(args):
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


def main():
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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
