from typing import Any

"""
ImpactGuard CLI - Command-line interface for the ImpactGuard library.
"""

import argparse
import json
import sys
from pathlib import Path


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract function signatures from source files.

    Supports all registered languages (Python, TypeScript, …).  Language is
    detected from the file extension unless ``--language`` is specified.
    """
    files = (
        args.files
        if args.files
        else [f for f in sys.stdin.read().splitlines() if f.strip()]
    )

    if not files:
        print("Error: No input files provided", file=sys.stderr)
        return 1

    language: str | None = getattr(args, "language", None)

    from .languages.registry import get_extractor, get_extractor_by_language

    if language:
        extractor = get_extractor_by_language(language)
        if extractor is None:
            print(f"Error: Unknown language '{language}'", file=sys.stderr)
            return 1
        result = extractor.extract_signatures(files)
    else:
        # Group files by language extractor, fall back to Python for .py
        from collections import defaultdict
        by_extractor: dict[str, list[str]] = defaultdict(list)
        unknown: list[str] = []
        for f in files:
            ext = get_extractor(f)
            if ext is not None:
                by_extractor[ext.language].append(f)
            else:
                unknown.append(f)

        if unknown:
            print(
                f"Warning: no extractor for {len(unknown)} file(s); skipping: "
                + ", ".join(unknown[:5]),
                file=sys.stderr,
            )

        result = []
        for lang, lang_files in by_extractor.items():
            lang_ext = get_extractor_by_language(lang)
            if lang_ext is not None:
                result.extend(lang_ext.extract_signatures(lang_files))
        result.sort(key=lambda x: x.get("fqname", ""))

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
    import os
    import tempfile as _tmpmod
    from .risk_gate import run as risk_main

    pipe: bool = getattr(args, "pipe", False)
    diff_path: str | None = getattr(args, "diff", None)
    _tmp_path: str | None = None

    if pipe:
        if not sys.stdin.isatty():
            diff_text = sys.stdin.read()
        else:
            print("Error: --pipe requires data on stdin", file=sys.stderr)
            return 1
        with _tmpmod.NamedTemporaryFile(
            mode="w", suffix=".diff", prefix="impactguard_pipe_", delete=False
        ) as _tmp:
            _tmp.write(diff_text)
            _tmp_path = _tmp.name
            diff_path = _tmp_path

    if not diff_path:
        print("Error: provide a diff path or use --pipe", file=sys.stderr)
        return 1

    try:
        return risk_main(diff_path, args.runtime, args.output, lambda_=getattr(args, "lam", 1.0))
    finally:
        if _tmp_path is not None:
            try:
                os.unlink(_tmp_path)
            except OSError:
                pass


def cmd_report(args: argparse.Namespace) -> int:
    """Generate HTML report from risk JSON."""
    from .generate_report import main as report_main

    report_main(args.report, args.output)
    return 0


def cmd_enforce(args: argparse.Namespace) -> int:
    """Enforce gate - block on HIGH risk."""
    import os
    import tempfile as _tmpmod
    from .enforce_gate import enforce

    pipe: bool = getattr(args, "pipe", False)
    diff_path: str | None = getattr(args, "diff", None)
    _tmp_path: str | None = None

    if pipe:
        if not sys.stdin.isatty():
            diff_text = sys.stdin.read()
        else:
            print("Error: --pipe requires data on stdin", file=sys.stderr)
            return 1
        # Write stdin content to a temp file so enforce() can consume it
        with _tmpmod.NamedTemporaryFile(
            mode="w", suffix=".diff", prefix="impactguard_pipe_", delete=False
        ) as _tmp:
            _tmp.write(diff_text)
            _tmp_path = _tmp.name
            diff_path = _tmp_path

    if not diff_path:
        print("Error: provide a diff path or use --pipe", file=sys.stderr)
        return 1

    block_unknown: bool | None = getattr(args, "block_unknown", None) or None
    lam: float = getattr(args, "lam", 1.0)
    try:
        return enforce(diff_path, args.runtime, getattr(args, "output", None), block_unknown=block_unknown, lambda_=lam)
    finally:
        if _tmp_path is not None:
            try:
                os.unlink(_tmp_path)
            except OSError:
                pass


def cmd_extract_calls(args: argparse.Namespace) -> int:
    """Extract call sites from source files.

    Supports all registered languages (Python, TypeScript, …).  Language is
    detected from the file extension unless ``--language`` is specified.
    """
    files = (
        args.files
        if args.files
        else [f for f in sys.stdin.read().splitlines() if f.strip()]
    )

    if not files:
        print("Error: No input files provided", file=sys.stderr)
        return 1

    language: str | None = getattr(args, "language", None)

    from .languages.registry import get_extractor, get_extractor_by_language

    all_calls = []
    for f in files:
        if language:
            lang_ext = get_extractor_by_language(language)
            if lang_ext is None:
                print(f"Error: Unknown language '{language}'", file=sys.stderr)
                return 1
        else:
            lang_ext = get_extractor(f)
            if lang_ext is None:
                print(
                    f"Warning: no extractor for '{f}'; skipping",
                    file=sys.stderr,
                )
                continue
        all_calls.extend(lang_ext.extract_calls(Path(f)))

    print(json.dumps(all_calls, indent=2))
    return 0


def cmd_runtime_impact(args: argparse.Namespace) -> int:
    """Analyze runtime impact of signature changes."""
    from .runtime_impact import analyze

    issues = analyze(args.signatures, args.calls)
    print(json.dumps(issues, indent=2))
    return 0


# Whitelist of allowed modules for tracing - used by cmd_trace
# This dictionary approach satisfies Semgrep's static analysis (no non-literal import)
_ALLOWED_TRACE_MODULES = {
    "impactguard": "impactguard",
    "impactguard.trace_calls": "impactguard.trace_calls",
    "impactguard.trace_calls_prod": "impactguard.trace_calls_prod",
    "tests": "tests",
    "tests.test_basic": "tests.test_basic",
    "tests.test_risk": "tests.test_risk",
    "tests.test_cli": "tests.test_cli",
    "tests.test_suggest_fixes": "tests.test_suggest_fixes",
    "tests.test_final_80": "tests.test_final_80",
    "tests.test_final_80_push": "tests.test_final_80_push",
}


def cmd_trace(args: argparse.Namespace) -> int:
    """Runtime tracing commands."""
    if args.trace_cmd == "install":
        import importlib
        import re

        from .trace_calls import install_tracer

        # Validate module name format
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9._]*$", args.module):
            print(f"Error: Invalid module name '{args.module}'", file=sys.stderr)
            return 1

        # Only allow modules in the whitelist (prevents arbitrary code execution)
        if args.module not in _ALLOWED_TRACE_MODULES:
            print(f"Error: Module '{args.module}' is not allowed for tracing", file=sys.stderr)
            return 1

        try:
            # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
            module = importlib.import_module(_ALLOWED_TRACE_MODULES[args.module])
        except ImportError as e:
            print(f"Error: Cannot import module '{args.module}': {e}", file=sys.stderr)
            return 1

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

    watch: bool = getattr(args, "watch", False)

    def _run_once() -> int:
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

            if "semver" in result:
                sv = result["semver"]
                print(f"\n=== Semver Recommendation ===")
                print(f"Bump: {sv.get('bump', 'patch').upper()}  — {sv.get('reason', '')}")

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

    if not watch:
        return _run_once()

    # ── Watch mode — re-run whenever any *.py file in old/new dirs changes ──
    import time
    import glob as _glob

    print(f"Watch mode enabled. Press Ctrl-C to stop.")

    def _mtimes() -> dict[str, float]:
        times: dict[str, float] = {}
        for pattern in [f"{args.old}/**/*.py", f"{args.new}/**/*.py",
                         f"{args.old}/*.py", f"{args.new}/*.py"]:
            for p in _glob.glob(pattern, recursive=True):
                try:
                    times[p] = Path(p).stat().st_mtime
                except OSError:
                    pass
        return times

    last_times = _mtimes()
    _run_once()
    try:
        while True:
            time.sleep(1)
            current = _mtimes()
            if current != last_times:
                last_times = current
                print("\n[watch] Change detected — re-running…\n")
                _run_once()
    except KeyboardInterrupt:
        print("\n[watch] Stopped.")
    return 0



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


def cmd_check_diff(args: argparse.Namespace) -> int:
    """Run ImpactGuard pipeline on a unified diff / patch file."""
    from .pipeline import run_pipeline_diff, run_pipeline_diff_content

    pipe: bool = getattr(args, "pipe", False)
    diff_path: str | None = getattr(args, "diff", None)

    if pipe:
        if not sys.stdin.isatty():
            diff_text = sys.stdin.read()
        else:
            print("Error: --pipe requires data on stdin", file=sys.stderr)
            return 1
        print("Analyzing diff from stdin")
        try:
            result = run_pipeline_diff_content(
                diff_text=diff_text,
                runtime_path=getattr(args, "runtime", None),
                output_dir=getattr(args, "output", None),
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        if not diff_path:
            print("Error: provide a diff path or use --pipe", file=sys.stderr)
            return 1
        print(f"Analyzing diff: {diff_path}")
        try:
            result = run_pipeline_diff(
                diff_path=diff_path,
                runtime_path=getattr(args, "runtime", None),
                output_dir=getattr(args, "output", None),
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    print("\n=== Comparison ===")
    comparison = result.get("comparison", {})
    print(f"Breaking changes: {len(comparison.get('breaking', []))}")
    print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")

    if "semver" in result:
        sv = result["semver"]
        print("\n=== Semver Recommendation ===")
        print(f"Bump: {sv.get('bump', 'patch').upper()}  — {sv.get('reason', '')}")

    if "risk" in result:
        risk_items = result["risk"]
        high = sum(1 for r in risk_items if r.get("risk") == "HIGH")
        print("\n=== Risk Analysis ===")
        print(f"HIGH risk: {high}")

    output = getattr(args, "output", None)
    if output and "report_html" in result:
        from pathlib import Path as _Path
        output_path = _Path(output)
        report_path = str(output_path / "impact_report.html") if output_path.is_dir() else output
        with open(report_path, "w") as f:
            f.write(result["report_html"])
        print(f"\nReport written to {report_path}")

    return 1 if comparison.get("breaking") else 0


def cmd_check_commit(args: argparse.Namespace) -> int:
    """Run ImpactGuard pipeline on a single git commit vs its parent."""
    from .pipeline import run_pipeline_commit

    print(f"Analyzing commit: {args.commit_ref}")

    try:
        result = run_pipeline_commit(
            commit_ref=args.commit_ref,
            files=getattr(args, "files", None),
            runtime_path=getattr(args, "runtime", None),
            output_path=getattr(args, "output", None),
        )
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print("\n=== Comparison ===")
    comparison = result.get("comparison", {})
    print(f"Breaking changes: {len(comparison.get('breaking', []))}")
    print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")

    if "semver" in result:
        sv = result["semver"]
        print("\n=== Semver Recommendation ===")
        print(f"Bump: {sv.get('bump', 'patch').upper()}  — {sv.get('reason', '')}")

    if "risk" in result:
        risk_items = result["risk"]
        high = sum(1 for r in risk_items if r.get("risk") == "HIGH")
        print("\n=== Risk Analysis ===")
        print(f"HIGH risk: {high}")

    output = getattr(args, "output", None)
    if output and "report_html" in result:
        print(f"\nReport written to {output}")

    return 1 if comparison.get("breaking") else 0


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


def cmd_suggest(args: argparse.Namespace) -> int:
    """Generate fix suggestions for a risk report."""
    import json
    from .suggest_fixes import suggest

    try:
        report = json.load(open(args.report))
    except Exception as e:
        print(f"Error reading report: {e}", file=sys.stderr)
        return 1

    all_suggestions: list[str] = []
    for item in report:
        sug = suggest(item, [item])
        all_suggestions.extend(sug)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(all_suggestions, f, indent=2)
    else:
        for s in all_suggestions:
            print(s)

    return 0


def cmd_patch(args: argparse.Namespace) -> int:
    """Generate CST-based patches for a source file."""
    from pathlib import Path
    from .cst_patch import patch_function, patch_call

    try:
        source = Path(args.file).read_text()
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return 1

    if args.patch_type == "function":
        result, err = patch_function(source, args.func_name, args.param_name)
    else:
        result, err = patch_call(source, args.func_name, args.param_name)

    if err:
        print(f"Patch error: {err}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(result or "")
    else:
        print(result)

    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """Manage ImpactGuard baselines."""
    from .baseline import (
        save_baseline,
        load_baseline,
        compare_with_baseline,
        baseline_exists,
        DEFAULT_BASELINE_PATH,
    )

    subcommand: str = args.baseline_cmd or "status"
    baseline_path: str | None = getattr(args, "baseline_path", None)

    if subcommand == "save":
        files = getattr(args, "files", None) or []
        if not files:
            # Collect all tracked Python files
            import glob as _glob
            files = list(_glob.glob("**/*.py", recursive=True))
            if not files:
                print("Error: No Python files found", file=sys.stderr)
                return 1

        import datetime
        metadata = {
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "files_count": len(files),
        }
        saved = save_baseline(files, baseline_path, metadata)
        print(f"Baseline saved: {saved} ({len(files)} file(s))")
        return 0

    elif subcommand == "status":
        effective = baseline_path or DEFAULT_BASELINE_PATH
        if baseline_exists(effective):
            data = load_baseline(effective)
            meta = data.get("metadata", {})
            sigs = data.get("signatures", [])
            print(f"Baseline: {effective}")
            print(f"  Functions: {len(sigs)}")
            if meta.get("saved_at"):
                print(f"  Saved at:  {meta['saved_at']}")
        else:
            print(f"No baseline found at: {effective}")
            print("Run `impactguard baseline save` to create one.")
        return 0

    elif subcommand == "compare":
        files = getattr(args, "files", None) or []
        if not files:
            import glob as _glob
            files = list(_glob.glob("**/*.py", recursive=True))
            if not files:
                print("Error: No Python files found", file=sys.stderr)
                return 1

        try:
            result = compare_with_baseline(files, baseline_path)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        comparison = result["comparison"]
        semver = result["semver"]
        print(f"Breaking changes:     {len(comparison.get('breaking', []))}")
        print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
        print(f"Semver recommendation: {semver.get('bump', 'patch').upper()} — {semver.get('reason', '')}")

        for item in comparison.get("breaking", []):
            print(f"  ⚠ {item}")

        output = getattr(args, "output", None)
        if output:
            import json
            with open(output, "w") as f:
                json.dump(result, f, indent=2)
            print(f"\nResult written to {output}")

        return 1 if comparison.get("breaking") else 0

    print(f"Unknown baseline subcommand: {subcommand}", file=sys.stderr)
    return 1


def cmd_semver(args: argparse.Namespace) -> int:
    """Suggest a semver bump from two signature snapshots."""
    from .compare_signatures import compare
    from .semver import format_semver_recommendation

    result = compare(args.old, args.new)
    rec = format_semver_recommendation(result, getattr(args, "current_version", None))

    print(f"Recommended bump: {rec['bump'].upper()}")
    print(f"Reason: {rec['reason']}")
    print(f"Breaking changes:     {rec['breaking_count']}")
    print(f"Non-breaking changes: {rec['nonbreaking_count']}")
    if "next_version" in rec:
        print(f"Next version:         {rec['next_version']}")

    output = getattr(args, "output", None)
    if output:
        import json
        with open(output, "w") as f:
            json.dump(rec, f, indent=2)

    return 0



def cmd_report_markdown(args: argparse.Namespace) -> int:
    """Generate a markdown PR-comment summary from a risk report JSON."""
    from .generate_report import generate_markdown_from_file

    output: str | None = getattr(args, "output", None)
    md = generate_markdown_from_file(args.report, output_path=output)
    if not output:
        print(md)
    else:
        print(f"Markdown report written to {output}")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    """Manage patch-outcome feedback for confidence calibration."""
    from .feedback import (
        record_outcome,
        get_stats,
        load_outcomes,
        compute_calibrated_weights,
        apply_weights_to_config,
    )

    subcmd: str = getattr(args, "feedback_cmd", "") or "stats"

    if subcmd == "record":
        accepted: bool = not getattr(args, "rejected", False)
        record_outcome(
            patch_id=args.patch_id,
            accepted=accepted,
            change_type=getattr(args, "change_type", None),
            feedback_path=getattr(args, "feedback_path", None),
        )
        status = "accepted" if accepted else "rejected"
        print(f"Recorded patch '{args.patch_id}' as {status}.")
        return 0

    if subcmd == "stats":
        stats = get_stats(getattr(args, "feedback_path", None))
        print(f"Total recorded: {stats['total']}")
        print(f"Accepted:       {stats['accepted']}")
        print(f"Rejected:       {stats['rejected']}")
        rate = stats["acceptance_rate"]
        print(f"Acceptance rate: {rate:.0%}")
        if stats["by_change_type"]:
            print("\nBy change type:")
            for ct, r in sorted(stats["by_change_type"].items()):
                print(f"  {ct}: {r:.0%}")
        return 0

    if subcmd == "calibrate":
        outcomes = load_outcomes(getattr(args, "feedback_path", None))
        weights = compute_calibrated_weights(outcomes)
        if not weights:
            print("Not enough data for calibration (need ≥ 5 outcomes per category).")
            return 0
        config_path: str = getattr(args, "config_path", None) or "impactguard.toml"
        ok = apply_weights_to_config(weights, config_path)
        if ok:
            print(f"Calibrated weights applied to {config_path}:")
            for k, v in weights.items():
                print(f"  {k} = {v:.4f}")
        else:
            print(f"Error: could not write to {config_path}", file=sys.stderr)
            return 1
        return 0

    print(f"Unknown feedback subcommand: {subcmd}", file=sys.stderr)
    return 1


def cmd_baseline_tagged(args: argparse.Namespace) -> int:
    """Handle tagged baseline sub-subcommands: save --tag, list, compare --from."""
    from .baseline import (
        save_tagged_baseline,
        list_baselines,
        compare_with_tagged_baseline,
        delete_tagged_baseline,
    )

    subcmd: str = getattr(args, "tagged_cmd", "") or "list"
    history_path: str | None = getattr(args, "history_path", None)

    if subcmd == "list":
        entries = list_baselines(history_path)
        if not entries:
            print("No tagged baselines stored yet.")
        for e in entries:
            meta = e.get("metadata") or {}
            saved_at = meta.get("saved_at", "")
            print(f"  {e['tag']:20s}  {e['signature_count']:4d} signatures  {saved_at}")
        return 0

    if subcmd == "save":
        import datetime
        import glob as _glob

        tag: str = args.tag
        files = getattr(args, "files", None) or []
        if not files:
            files = list(_glob.glob("**/*.py", recursive=True))
            if not files:
                print("Error: No Python files found", file=sys.stderr)
                return 1

        metadata = {
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "files_count": len(files),
        }
        try:
            saved = save_tagged_baseline(tag, files, history_path, metadata)
            print(f"Tagged baseline '{tag}' saved to {saved} ({len(files)} file(s))")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if subcmd == "compare":
        import glob as _glob

        tag_from: str = args.tag_from
        files = getattr(args, "files", None) or []
        if not files:
            files = list(_glob.glob("**/*.py", recursive=True))
            if not files:
                print("Error: No Python files found", file=sys.stderr)
                return 1
        try:
            result = compare_with_tagged_baseline(tag_from, files, history_path)
        except (FileNotFoundError, KeyError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        comparison = result["comparison"]
        semver = result["semver"]
        print(f"Comparing against baseline tag '{tag_from}':")
        print(f"  Breaking changes:     {len(comparison.get('breaking', []))}")
        print(f"  Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
        print(f"  Semver recommendation: {semver.get('bump', 'patch').upper()}")
        for item in comparison.get("breaking", []):
            print(f"  ⚠ {item}")

        output = getattr(args, "output", None)
        if output:
            with open(output, "w") as f:
                json.dump(result, f, indent=2)
            print(f"\nResult written to {output}")

        return 1 if comparison.get("breaking") else 0

    if subcmd == "delete":
        tag_del: str = args.tag
        removed = delete_tagged_baseline(tag_del, history_path)
        if removed:
            print(f"Tagged baseline '{tag_del}' deleted.")
        else:
            print(f"Tag '{tag_del}' not found.", file=sys.stderr)
            return 1
        return 0

    print(f"Unknown tagged-baseline subcommand: {subcmd}", file=sys.stderr)
    return 1


def main() -> int:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="impactguard",
        description="ImpactGuard - API impact analyzer for Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # extract subcommand
    extract_parser = subparsers.add_parser(
        "extract", help="Extract function signatures from source files"
    )
    extract_parser.add_argument(
        "files", nargs="*",
        help="Source files to analyze (Python, TypeScript, …)",
    )
    extract_parser.add_argument(
        "--language", "-l",
        help="Force a specific language (e.g. python, typescript); "
             "auto-detected from extension when omitted",
    )
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
    risk_parser.add_argument("diff", nargs="?", help="Diff text file (omit with --pipe)")
    risk_parser.add_argument("runtime", help="Runtime data JSON file")
    risk_parser.add_argument("output", help="Output report JSON file")
    risk_parser.add_argument(
        "--pipe", action="store_true",
        help="Read diff from stdin instead of a file (e.g. diff A B | impactguard risk --pipe ...)",
    )
    risk_parser.add_argument(
        "--lambda", dest="lam", type=float, default=1.0, metavar="LAMBDA",
        help="Sensitivity multiplier (default: 1.0). >1 increases sensitivity; <1 decreases it.",
    )
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
    enforce_parser.add_argument("diff", nargs="?", help="Diff text file (omit with --pipe)")
    enforce_parser.add_argument("runtime", help="Runtime data JSON file")
    enforce_parser.add_argument("-o", "--output", help="Output report JSON file")
    enforce_parser.add_argument(
        "--block-unknown",
        action="store_true",
        help="Treat UNKNOWN risk as a blocking condition (same as HIGH)",
    )
    enforce_parser.add_argument(
        "--pipe", action="store_true",
        help="Read diff from stdin instead of a file (e.g. diff A B | impactguard enforce --pipe ...)",
    )
    enforce_parser.add_argument(
        "--lambda", dest="lam", type=float, default=1.0, metavar="LAMBDA",
        help="Sensitivity multiplier (default: 1.0). >1 increases sensitivity; <1 decreases it.",
    )
    enforce_parser.set_defaults(func=cmd_enforce)

    # suggest subcommand
    suggest_parser = subparsers.add_parser("suggest", help="Generate fix suggestions from risk report")
    suggest_parser.add_argument("report", help="Risk report JSON file")
    suggest_parser.add_argument("-o", "--output", help="Output JSON file for suggestions")
    suggest_parser.set_defaults(func=cmd_suggest)

    # patch subcommand
    patch_parser = subparsers.add_parser("patch", help="Generate CST-based patches")
    patch_parser.add_argument("file", help="Python source file to patch")
    patch_parser.add_argument("func_name", help="Function name to patch")
    patch_parser.add_argument("param_name", help="Parameter name to patch")
    patch_parser.add_argument(
        "--type", dest="patch_type", choices=["function", "call"], default="function",
        help="Patch type: 'function' adds default, 'call' fixes call site"
    )
    patch_parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    patch_parser.set_defaults(func=cmd_patch)

    # extract-calls subcommand
    extract_calls_parser = subparsers.add_parser(
        "extract-calls", help="Extract call sites from source files"
    )
    extract_calls_parser.add_argument(
        "files", nargs="*",
        help="Source files to analyze (Python, TypeScript, …)",
    )
    extract_calls_parser.add_argument(
        "--language", "-l",
        help="Force a specific language; auto-detected from extension when omitted",
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
    check_parser.add_argument(
        "--watch", action="store_true",
        help="Re-run automatically when source files change",
    )
    check_parser.set_defaults(func=cmd_check)

    # check-diff subcommand (unified diff / patch file)
    check_diff_parser = subparsers.add_parser(
        "check-diff", help="Run full pipeline on a unified diff / patch file"
    )
    check_diff_parser.add_argument(
        "diff", nargs="?", help="Path to unified diff / patch file (omit with --pipe)"
    )
    check_diff_parser.add_argument(
        "--runtime", help="Runtime data JSON (optional)"
    )
    check_diff_parser.add_argument(
        "-o", "--output", help="Output directory or HTML report path"
    )
    check_diff_parser.add_argument(
        "--pipe", action="store_true",
        help="Read diff from stdin instead of a file (e.g. diff A B | impactguard check-diff --pipe)",
    )
    check_diff_parser.set_defaults(func=cmd_check_diff)

    # check-commit subcommand (single commit vs its parent)
    check_commit_parser = subparsers.add_parser(
        "check-commit", help="Run full pipeline on a single git commit vs its parent"
    )
    check_commit_parser.add_argument(
        "commit_ref", help="Git reference (commit SHA, branch, tag) to analyze"
    )
    check_commit_parser.add_argument(
        "--files", nargs="+", help="Specific files to compare (relative to repo root)"
    )
    check_commit_parser.add_argument(
        "--runtime", help="Runtime data JSON (optional)"
    )
    check_commit_parser.add_argument(
        "-o", "--output", help="Output path for HTML report"
    )
    check_commit_parser.set_defaults(func=cmd_check_commit)

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

    # baseline subcommand
    baseline_parser = subparsers.add_parser(
        "baseline", help="Manage ImpactGuard signature baselines"
    )
    baseline_sub = baseline_parser.add_subparsers(
        dest="baseline_cmd", help="Baseline subcommands"
    )
    baseline_save = baseline_sub.add_parser("save", help="Save current signatures as baseline")
    baseline_save.add_argument("files", nargs="*", help="Python files to snapshot (default: all)")
    baseline_save.add_argument("--path", dest="baseline_path", help="Path to baseline JSON file")
    baseline_status = baseline_sub.add_parser("status", help="Show baseline info")
    baseline_status.add_argument("--path", dest="baseline_path", help="Path to baseline JSON file")
    baseline_compare = baseline_sub.add_parser("compare", help="Compare current code against baseline")
    baseline_compare.add_argument("files", nargs="*", help="Python files to compare (default: all)")
    baseline_compare.add_argument("--path", dest="baseline_path", help="Path to baseline JSON file")
    baseline_compare.add_argument("-o", "--output", help="Output JSON file for comparison result")
    baseline_parser.set_defaults(func=cmd_baseline)

    # semver subcommand
    semver_parser = subparsers.add_parser(
        "semver", help="Suggest semver bump from two signature snapshots"
    )
    semver_parser.add_argument("old", help="Old signatures JSON file")
    semver_parser.add_argument("new", help="New signatures JSON file")
    semver_parser.add_argument(
        "--current-version", dest="current_version", help="Current version string (e.g. 1.2.3)"
    )
    semver_parser.add_argument("-o", "--output", help="Output JSON file for recommendation")
    semver_parser.set_defaults(func=cmd_semver)

    # report-markdown subcommand
    report_md_parser = subparsers.add_parser(
        "report-markdown", help="Generate markdown PR comment from risk report JSON"
    )
    report_md_parser.add_argument("report", help="Risk report JSON file")
    report_md_parser.add_argument(
        "-o", "--output", help="Output markdown file (default: stdout)"
    )
    report_md_parser.set_defaults(func=cmd_report_markdown)

    # feedback subcommand
    feedback_parser = subparsers.add_parser(
        "feedback", help="Manage patch-outcome feedback for confidence calibration"
    )
    feedback_sub = feedback_parser.add_subparsers(
        dest="feedback_cmd", help="Feedback subcommands"
    )

    fb_record = feedback_sub.add_parser("record", help="Record a patch acceptance/rejection")
    fb_record.add_argument("patch_id", help="Patch identifier")
    _fb_outcome = fb_record.add_mutually_exclusive_group()
    _fb_outcome.add_argument(
        "--accepted", action="store_true", default=False, help="Mark patch as accepted"
    )
    _fb_outcome.add_argument(
        "--rejected", action="store_true", default=False, help="Mark patch as rejected"
    )
    fb_record.add_argument("--change-type", dest="change_type", help="Change category")
    fb_record.add_argument(
        "--feedback-path", dest="feedback_path", help="Feedback JSON file path"
    )

    fb_stats = feedback_sub.add_parser("stats", help="Show feedback statistics")
    fb_stats.add_argument(
        "--feedback-path", dest="feedback_path", help="Feedback JSON file path"
    )

    fb_calibrate = feedback_sub.add_parser(
        "calibrate", help="Calibrate patch-confidence weights from recorded outcomes"
    )
    fb_calibrate.add_argument(
        "--feedback-path", dest="feedback_path", help="Feedback JSON file path"
    )
    fb_calibrate.add_argument(
        "--config-path", dest="config_path", help="Path to impactguard.toml to update"
    )

    feedback_parser.set_defaults(func=cmd_feedback)

    # baseline tagged subcommand (history)
    history_parser = subparsers.add_parser(
        "history", help="Manage tagged release-history baselines"
    )
    history_sub = history_parser.add_subparsers(
        dest="tagged_cmd", help="History subcommands"
    )

    hist_list = history_sub.add_parser("list", help="List all tagged baselines")
    hist_list.add_argument("--history-path", dest="history_path", help="History JSON file path")

    hist_save = history_sub.add_parser("save", help="Save a tagged baseline snapshot")
    hist_save.add_argument("tag", help="Release tag (e.g. v1.2.0)")
    hist_save.add_argument("files", nargs="*", help="Python files to snapshot")
    hist_save.add_argument("--history-path", dest="history_path", help="History JSON file path")

    hist_compare = history_sub.add_parser(
        "compare", help="Compare current code against a tagged baseline"
    )
    hist_compare.add_argument("tag_from", help="Tag to compare against")
    hist_compare.add_argument("files", nargs="*", help="Python files to compare")
    hist_compare.add_argument("--history-path", dest="history_path", help="History JSON file path")
    hist_compare.add_argument("-o", "--output", help="Output JSON file for comparison result")

    hist_delete = history_sub.add_parser("delete", help="Delete a tagged baseline")
    hist_delete.add_argument("tag", help="Tag to delete")
    hist_delete.add_argument("--history-path", dest="history_path", help="History JSON file path")

    history_parser.set_defaults(func=cmd_baseline_tagged)


    if len(sys.argv) > 1 and sys.argv[1] not in [
        "extract", "compare", "analyze", "risk", "report", "report-markdown",
        "trace", "check", "check-commits", "check-diff", "check-commit",
        "install-hooks",
        "enforce", "extract-calls", "runtime-impact",
        "generate-changelog", "suggest", "patch",
        "baseline", "semver", "feedback", "history",
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
