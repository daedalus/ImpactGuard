from typing import Any

"""
ImpactGuard CLI - Command-line interface for the ImpactGuard library.
"""

import argparse
import json
import sys
from pathlib import Path


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


def cmd_risk(args: argparse.Namespace) -> int:
    """Run risk analysis pipeline."""
    from .risk_gate import run as risk_main

    return risk_main(args.diff, args.runtime, args.output)


def cmd_report(args: argparse.Namespace) -> int:
    """Generate HTML report from risk JSON."""
    from .generate_report import main as report_main

    report_main(args.report, args.output)
    return 0


def cmd_enforce(args: argparse.Namespace) -> int:
    """Enforce gate - block on HIGH risk."""
    from .enforce_gate import enforce

    return enforce(args.report)


def cmd_extract_calls(args: argparse.Namespace) -> int:
    """Extract call sites from Python files."""
    from .extract_calls import extract

    files = (
        args.files
        if args.files
        else [f for f in sys.stdin.read().splitlines() if f.strip()]
    )

    if not files:
        print("Error: No input files provided", file=sys.stderr)
        return 1

    all_calls = []
    for f in files:
        all_calls.extend(extract(Path(f)))

    print(json.dumps(all_calls, indent=2))
    return 0


def cmd_runtime_impact(args: argparse.Namespace) -> int:
    """Analyze runtime impact of signature changes."""
    from .runtime_impact import analyze

    issues = analyze(args.signatures, args.calls)
    print(json.dumps(issues, indent=2))
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
        print(
            f"Breaking changes: {len(result.get('comparison', {}).get('breaking', []))}"
        )
        print(
            f"Non-breaking changes: {len(result.get('comparison', {}).get('nonbreaking', []))}"
        )

        if "risk" in result:
            risk_items = result["risk"]
            high = sum(1 for r in risk_items if r.get("risk") == "HIGH")
            print(f"\n=== Risk Analysis ===")
            print(f"HIGH risk: {high}")

        if "report_html" in result:
            output = args.output or "impact_report.html"
            with open(output, "w") as f:
                f.write(result["report_html"])
            print(f"\nReport written to {output}")

        if "fixes" in result:
            fixes = result["fixes"]
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
            files=args.files if hasattr(args, "files") else None,
            runtime_path=args.runtime,
            output_path=args.output,
        )

        print(f"\n=== Comparison ===")
        comparison = result.get("comparison", {})
        print(f"Breaking changes: {len(comparison.get('breaking', []))}")
        print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")

        if "risk" in result:
            risk_items = result["risk"]
            high = sum(1 for r in risk_items if r.get("risk") == "HIGH")
            print(f"\n=== Risk Analysis ===")
            print(f"HIGH risk: {high}")

        if "report_html" in result and args.output:
            print(f"\nReport written to {args.output}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_install_hooks(args: argparse.Namespace) -> int:
    """Install git hooks for ImpactGuard."""
    import os
    import stat

    repo_path = Path(args.repo_path)
    git_dir = repo_path / ".git"

    if not git_dir.exists():
        print(f"Error: Not a git repository: {repo_path}")
        return 1

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    # Determine which hooks to install
    install_pre = args.pre or args.both or (not args.pre and not args.post and not args.both)
    install_post = args.post or args.both or (not args.pre and not args.post and not args.both)

    # Get the impactguard command path
    impactguard_cmd = "impactguard"  # Assume it's in PATH

    # Install pre-commit hook
    if install_pre:
        pre_commit_path = hooks_dir / "pre-commit"
        pre_commit_content = rf"""#!/bin/sh>
# Pre-commit hook for ImpactGuard>
# Runs signature extraction before commit>

# Extract signatures from staged Python files>
files=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$')>
if [ -n "$files" ]; then>
    echo "ImpactGuard: Extracting signatures...">
    $impactguard_cmd extract $files > /tmp/staged_sigs.json>
fi>

exit 0>
"""
        pre_commit_path.write_text(pre_commit_content)
        os.chmod(pre_commit_path, os.stat(pre_commit_path).st_mode | stat.S_IEXEC)
        print(f"Installed pre-commit hook: {pre_commit_path}")

    # Install post-commit hook
    if install_post:
        post_commit_path = hooks_dir / "post-commit"
        post_commit_path.write_text(rf"""#!/bin/sh>

# Post-commit hook for ImpactGuard>
# Ensures signature tracking is up to date>

# Skip if called from hook itself>
if [ "$SKIP_SIGNATURE_HOOK" = "1" ]; then>
    exit 0>
fi>

# Check if Python files changed>
changed=$(git diff-tree --no-commit-id --name-only -r HEAD | grep '\.py$' || echo "")>

if [ -n "$changed" ]; then>
    echo "ImpactGuard: Updating signature tracking...">
    
    # Extract signatures from all Python files>
    $impactguard_cmd extract $(git ls-files | grep '\.py$') > /tmp/impactguard_sigs_$$.json>
    
    # You can optionally commit the signatures or just keep them local>
    # For now, we just ensure the extraction runs successfully>
    if [ $? -eq 0 ]; then>
        echo "ImpactGuard: Signatures extracted successfully">
    else>
        echo "ImpactGuard: Warning - signature extraction failed">
    fi>
fi>

exit 0>
""")
        os.chmod(post_commit_path, os.stat(post_commit_path).st_mode | stat.S_IEXEC)
        print(f"Installed post-commit hook: {post_commit_path}")

    print(f"\nHooks installed successfully to {hooks_dir}")
    return 0


def cmd_generate_changelog(args: argparse.Namespace) -> int:
    """Generate changelog from signature diffs."""
    from .pipeline import generate_changelog

    try:
        changelog = generate_changelog(
            old_ref=args.old_ref if args.old_ref else None,
            new_ref=args.new_ref if args.new_ref else None,
            old_files=args.old_files if hasattr(args, "old_files") else None,
            new_files=args.new_files if hasattr(args, "new_files") else None,
            output_path=args.output,
        )
        print(changelog)
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
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract function signatures")
    extract_parser.add_argument("files", nargs="*", help="Python files to analyze")
    extract_parser.set_defaults(func=cmd_extract)

    # compare subcommand
    compare_parser = subparsers.add_parser("compare", help="Compare signature snapshots")
    compare_parser.add_argument("old", help="Old signatures JSON file")
    compare_parser.add_argument("new", help="New signatures JSON file")
    compare_parser.add_argument("-o", "--output", help="Output file for results")
    compare_parser.set_defaults(func=cmd_compare)

    # analyze subcommand
    analyze_parser = subparsers.add_parser("analyze", help="Analyze impact on call sites")
    analyze_parser.add_argument("signatures", help="Signatures JSON file")
    analyze_parser.add_argument("calls", help="Call sites JSON file")
    analyze_parser.add_argument(
        "runtime", nargs="?", help="Runtime data JSON file"
    )
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

    # enforce subcommand
    enforce_parser = subparsers.add_parser("enforce", help="Enforce gate - block on HIGH risk")
    enforce_parser.add_argument("report", help="Risk report JSON file")
    enforce_parser.set_defaults(func=cmd_enforce)

    # extract-calls subcommand
    extract_calls_parser = subparsers.add_parser(
        "extract-calls", help="Extract call sites from Python files"
    )
    extract_calls_parser.add_argument(
        "files", nargs="*", help="Python files to analyze"
    )
    extract_calls_parser.set_defaults(func=cmd_extract_calls)

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

    # check subcommand (pipeline mode)
    check_parser = subparsers.add_parser(
        "check", help="Run full ImpactGuard pipeline check"
    )
    check_parser.add_argument("old", help="Old Python file/directory")
    check_parser.add_argument("new", help="New Python file/directory")
    check_parser.add_argument(
        "runtime", nargs="?", help="Runtime data JSON (optional)"
    )
    check_parser.add_argument(
        "output", nargs="?", default="impact_report.html", help="Output HTML report"
    )
    check_parser.set_defaults(func=cmd_check)

    # check-commits subcommand (git commit comparison)
    check_commits_parser = subparsers.add_parser(
        "check-commits", help="Compare two git commits"
    )
    check_commits_parser.add_argument(
        "old_ref", help="Old git reference (commit, branch, tag)"
    )
    check_commits_parser.add_argument(
        "new_ref", help="New git reference (commit, branch, tag)"
    )
    check_commits_parser.add_argument(
        "--files", nargs="+", help="Specific files to compare (relative to repo root)"
    )
    check_commits_parser.add_argument(
        "runtime", nargs="?", help="Runtime data JSON (optional)"
    )
    check_commits_parser.add_argument(
        "output", nargs="?", help="Output HTML report"
    )
    check_commits_parser.set_defaults(func=cmd_check_commits)

    # install-hooks subcommand
    hooks_parser = subparsers.add_parser(
        "install-hooks", help="Install git hooks for ImpactGuard"
    )
    hooks_parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to git repository (default: current directory)",
    )
    hooks_parser.add_argument(
        "--pre",
        action="store_true",
        help="Install pre-commit hook only",
    )
    hooks_parser.add_argument(
        "--post",
        action="store_true",
        help="Install post-commit hook only",
    )
    hooks_parser.add_argument(
        "--both",
        action="store_true",
        help="Install both hooks (default)",
    )
    hooks_parser.set_defaults(func=cmd_install_hooks)

    # generate-changelog subcommand
    changelog_parser = subparsers.add_parser(
        "generate-changelog", help="Generate changelog from signature diffs"
    )
    changelog_parser.add_argument(
        "old_ref", nargs="?", help="Old git reference (commit, branch, tag)"
    )
    changelog_parser.add_argument(
        "new_ref", nargs="?", help="New git reference (commit, branch, tag)"
    )
    changelog_parser.add_argument(
        "--old-files", nargs="+", help="Old Python files (alternative to old_ref)"
    )
    changelog_parser.add_argument(
        "--new-files", nargs="+", help="New Python files (alternative to new_ref)"
    )
    changelog_parser.add_argument(
        "output", nargs="?", help="Output file for changelog"
    )
    changelog_parser.set_defaults(func=cmd_generate_changelog)

    # Make 'check' the default if no subcommand provided but args look like paths
    if len(sys.argv) > 1 and sys.argv[1] not in [
        "extract", "compare", "analyze", "risk", "report", "trace",
        "check", "check-commits", "install-hooks",
        "enforce", "extract-calls", "runtime-impact",
        "generate-changelog",
    ] and not sys.argv[1].startswith("-"):
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
