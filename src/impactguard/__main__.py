"""
ImpactGuard CLI - Command-line interface for the ImpactGuard library.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract function signatures from source files.

    Supports all registered languages (Python, TypeScript, …).  Language is
    detected from the file extension unless ``--language`` is specified.
    """
    if args.files:
        files = args.files
    elif not sys.stdin.isatty():
        files = [f for f in sys.stdin.read().splitlines() if f.strip()]
    else:
        files = []

    if not files:
        print("Error: No input files provided", file=sys.stderr)
        return 1

    incremental: bool = getattr(args, "incremental", False)
    if incremental:
        try:
            from .call_graph import CallGraphDB

            cwd = Path.cwd()
            db = CallGraphDB(cwd)
            stale = db.filter_stale(files)
            skipped = len(files) - len(stale)
            if skipped:
                print(
                    f"Incremental: {skipped} file(s) unchanged, skipping",
                    file=sys.stderr,
                )
            files = stale
        except Exception as exc:
            print(
                f"Warning: --incremental call graph unavailable ({exc}); "
                "falling back to full extraction",
                file=sys.stderr,
            )

    language: str | None = getattr(args, "language", None)
    strict: bool = getattr(args, "strict", False)

    from .languages.lib.registry import get_extractor, get_extractor_by_language

    def _sig_extract(extractor: object, file_list: list[str]) -> list[dict[str, Any]]:
        """Call extract_signatures, forwarding strict= when supported."""
        import inspect

        method = getattr(extractor, "extract_signatures", None)
        if method is None:
            print(
                f"Warning: extractor {extractor!r} has no extract_signatures method; skipping",
                file=sys.stderr,
            )
            return []
        if strict and "strict" in inspect.signature(method).parameters:
            return method(file_list, strict=strict)
        return method(file_list)

    if language:
        extractor = get_extractor_by_language(language)
        if extractor is None:
            print(f"Error: Unknown language '{language}'", file=sys.stderr)
            return 1
        result = _sig_extract(extractor, files)
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
                result.extend(_sig_extract(lang_ext, lang_files))
        result.sort(key=lambda x: x.get("fqname", ""))

    print(json.dumps(result, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare two signature snapshots or source files."""
    from .compare_signatures import compare

    # Use getattr for backward compatibility (tests may not have json attribute)
    use_json = getattr(args, "json", False)

    if use_json:
        # JSON mode: compare two JSON files directly (original behavior)
        try:
            result = compare(args.old, args.new)
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        # Source mode: extract signatures from source files, then compare
        from .languages.lib.registry import get_extractor

        def _extract_file(file_path: str) -> list[dict[str, Any]]:
            """Extract signatures from a single source file."""
            extractor = get_extractor(file_path)
            if extractor is None:
                print(
                    f"Error: No extractor found for file '{file_path}'",
                    file=sys.stderr,
                )
                return []
            method = getattr(extractor, "extract_signatures", None)
            if method is None:
                print(
                    f"Error: Extractor for '{file_path}' has no extract_signatures method",
                    file=sys.stderr,
                )
                return []
            return method([file_path])

        old_sigs = _extract_file(args.old)
        new_sigs = _extract_file(args.new)

        if not old_sigs:
            print(
                f"Error: Failed to extract signatures from '{args.old}'",
                file=sys.stderr,
            )
            return 1
        if not new_sigs:
            print(
                f"Error: Failed to extract signatures from '{args.new}'",
                file=sys.stderr,
            )
            return 1

        result = compare(old_sigs, new_sigs)

    print(f"Breaking changes: {len(result['breaking'])}")
    print(f"Non-breaking changes: {len(result['nonbreaking'])}")
    for item in result.get("breaking", []):
        print(f"  \u26a0 {item}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)

    return 1 if result["breaking"] else 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Analyze impact of signature changes on call sites."""
    from .impact_analysis import analyze

    try:
        result = analyze(args.signatures, args.calls, args.runtime)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_risk(args: argparse.Namespace) -> "int | list[dict[str, Any]]":
    """Run risk analysis pipeline."""
    import os
    import tempfile as _tmpmod

    from .risk_gate import run as risk_main

    pipe: bool = getattr(args, "pipe", False)
    diff_path: str | None = getattr(args, "diff", None)
    _tmp_path: str | None = None

    if pipe:
        if not sys.stdin.isatty():
            try:
                diff_text = sys.stdin.read()
            except UnicodeDecodeError:
                print(
                    "Error: --pipe received binary data; expected text diff.",
                    file=sys.stderr,
                )
                return 1
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
        return risk_main(
            diff_path, args.runtime, args.output, lambda_=getattr(args, "lambda_factor", 1.0)
        )
    finally:
        if _tmp_path is not None:
            try:
                os.unlink(_tmp_path)
            except OSError:
                _log.debug("Failed to clean up temp file: %s", _tmp_path)


def cmd_report(args: argparse.Namespace) -> int:
    """Generate HTML report from risk JSON."""
    from .generate_report import generate_main as report_main

    try:
        report_main(args.report, args.output)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
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
            try:
                diff_text = sys.stdin.read()
            except UnicodeDecodeError:
                print(
                    "Error: --pipe received binary data; expected text diff.",
                    file=sys.stderr,
                )
                return 1
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
    lambda_factor: float = getattr(args, "lambda_factor", 1.0)
    try:
        return enforce(
            diff_path,
            args.runtime,
            getattr(args, "output", None),
            block_unknown=block_unknown,
            lambda_=lambda_factor,
        )
    finally:
        if _tmp_path is not None:
            try:
                os.unlink(_tmp_path)
            except OSError:
                _log.debug("Failed to clean up temp file: %s", _tmp_path)


def cmd_extract_calls(args: argparse.Namespace) -> int:
    """Extract call sites from source files.

    Supports all registered languages (Python, TypeScript, …).  Language is
    detected from the file extension unless ``--language`` is specified.
    """
    if args.files:
        files = args.files
    elif not sys.stdin.isatty():
        files = [f for f in sys.stdin.read().splitlines() if f.strip()]
    else:
        files = []

    if not files:
        print("Error: No input files provided", file=sys.stderr)
        return 1

    language: str | None = getattr(args, "language", None)

    from .languages.lib.registry import get_extractor, get_extractor_by_language

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
            print(
                f"Error: Module '{args.module}' is not allowed for tracing",
                file=sys.stderr,
            )
            return 1

        try:
            # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
            module = importlib.import_module(args.module)
            # Verify the imported module name matches exactly (prevents submodule bypass)
            if getattr(module, "__name__", None) != args.module:
                print(
                    f"Error: Module name mismatch for '{args.module}'",
                    file=sys.stderr,
                )
                return 1
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
    suggest_patch: bool = getattr(args, "suggest_patch", False)
    show_patch: bool = getattr(args, "show_patch", False)
    generate_fixes: bool = not bool(getattr(args, "no_generate_fixes", False))
    apply_safe_fixes: bool = bool(getattr(args, "apply_safe_fixes", False))
    use_call_graph: bool = getattr(args, "use_call_graph", False)
    conservative: bool = getattr(args, "conservative", False)

    def _run_once() -> int:
        print(f"Checking impact: {args.old} → {args.new}")
        try:
            result = quick_check(
                args.old,
                args.new,
                args.runtime,
                suggest_patch=suggest_patch,
                show_patch=show_patch,
                generate_fixes=generate_fixes,
                apply_safe_fixes=apply_safe_fixes,
                use_call_graph=use_call_graph,
                conservative=conservative,
            )
            comparison = result.get("comparison", {})
            print("\n=== Comparison ===")
            print(f"Breaking changes: {len(comparison.get('breaking', []))}")
            print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
            _print_breaking_details(comparison)

            if "semver" in result:
                _print_semver(result["semver"])

            _print_risk_analysis(result)

            if "report_html" in result:
                output = args.output or "impact_report.html"
                with open(output, "w") as f:
                    f.write(result["report_html"])
                print(f"\nReport written to {output}")

            sarif_path = getattr(args, "report_sarif", None)
            if sarif_path:
                _write_sarif_output(result, sarif_path)

            _print_fixes(result)

            if suggest_patch:
                _print_patches(result)

            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

    if not watch:
        return _run_once()

    # ── Watch mode — re-run whenever any supported source file changes ─────
    import glob as _glob
    import time

    from .languages.lib.registry import list_extensions as _list_exts

    print("Watch mode enabled. Press Ctrl-C to stop.")

    def _mtimes() -> dict[str, float]:
        times: dict[str, float] = {}
        extensions = _list_exts()  # all registered language extensions
        for ext in extensions:
            ext_glob = f"*{ext}"
            for base in (args.old, args.new):
                for pattern in [
                    f"{base}/**/{ext_glob}",
                    f"{base}/{ext_glob}",
                ]:
                    for p in _glob.glob(pattern, recursive=True):
                        try:
                            times[p] = Path(p).stat().st_mtime
                        except OSError:
                            _log.debug("Failed to stat file for watch mode: %s", p)
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


def _write_sarif_output(result: dict[str, Any], sarif_path: str) -> None:
    """Write SARIF report from pipeline result if risk data is available."""
    risk_data = result.get("risk")
    if not risk_data:
        return
    import json

    from .sarif import generate_sarif

    sarif = generate_sarif(risk_data)
    with open(sarif_path, "w") as f:
        json.dump(sarif, f, indent=2)
    print(f"SARIF report written to {sarif_path}")


def _print_breaking_details(comparison: dict[str, Any]) -> None:
    """Print breaking and non-breaking change items with clear separation."""
    breaking = comparison.get("breaking", [])
    nonbreaking = comparison.get("nonbreaking", [])
    if breaking:
        print("  Breaking:")
        for item in breaking:
            print(f"    \u26a0 {item}")
    if nonbreaking:
        print("  Non-breaking:")
        for item in nonbreaking:
            print(f"    \u2795 {item}")


def _print_semver(semver: dict[str, Any]) -> None:
    bump = semver.get("bump", "patch").upper()
    reason = semver.get("reason", "")
    print("\n=== Semver Recommendation ===")
    print(f"Bump: {bump}  — {reason}")


def _print_risk_analysis(result: dict[str, Any]) -> None:
    risk_items = result.get("risk")
    if not risk_items:
        return
    high = sum(1 for r in risk_items if r.get("risk") == "HIGH")
    med = sum(1 for r in risk_items if r.get("risk") == "MEDIUM")
    low = sum(1 for r in risk_items if r.get("risk") == "LOW")
    unk = sum(1 for r in risk_items if r.get("risk") == "UNKNOWN")
    print("\n=== Risk Analysis ===")
    print(f"HIGH: {high}   MEDIUM: {med}   LOW: {low}   UNKNOWN: {unk}")
    for item in risk_items:
        if item.get("risk") in ("HIGH", "UNKNOWN"):
            func = item.get("function", "?")
            change = item.get("raw_change") or item.get("change", "?")
            print(f"  \u26a0 [{item['risk']}] {func} — {change}")


def _print_fixes(result: dict[str, Any]) -> None:
    fixes = result.get("fixes")
    if not fixes:
        return
    print(f"\n=== Suggested Fixes ({len(fixes)}) ===")
    for fix in fixes[:5]:
        print(f"  - {fix}")


def _print_patches(result: dict[str, Any]) -> None:
    patches = result.get("patches")
    if not patches:
        return
    print(f"\n=== Generated Patches ({len(patches)}) ===")
    for func_name, patch_info in patches.items():
        print(f"  - {func_name}: {patch_info.get('type', 'unknown')} patch")
        print(f"    File: {patch_info.get('file', '')}")


def _print_analysis_status(result: dict[str, Any]) -> None:
    status = result.get("analysis_status")
    if not status:
        return
    counters = status.get("counters", {})
    print("\n=== Analysis Status ===")
    print(f"Status: {status.get('status', 'unknown').upper()}")
    print(
        "Counters: "
        f"parse_failures={counters.get('parse_failures', 0)}, "
        f"skipped_files={counters.get('skipped_files', 0)}, "
        f"fallback_used={counters.get('fallback_used', 0)}, "
        f"call_extraction_failures={counters.get('call_extraction_failures', 0)}, "
        f"runtime_data_issues={counters.get('runtime_data_issues', 0)}"
    )
    runtime = status.get("runtime", {})
    if runtime:
        print(f"Runtime state: {runtime.get('state', 'unknown')}")


def _print_gate_summary(result: dict[str, Any]) -> None:
    gate = result.get("gate")
    if not gate:
        return
    print("\n=== Gate Summary ===")
    print(f"Blocked: {str(gate.get('blocked', False)).lower()}")
    reasons = gate.get("reasons", [])
    if not reasons:
        return
    print("Reasons:")
    for reason in reasons:
        print(f"  - {reason}")


def _print_check_result(
    result: dict[str, Any], args: argparse.Namespace, suggest_patch: bool
) -> None:
    comparison = result.get("comparison", {})
    print("\n=== Comparison ===")
    print(f"Breaking changes: {len(comparison.get('breaking', []))}")
    print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
    _print_breaking_details(comparison)

    _print_risk_analysis(result)
    _print_analysis_status(result)
    _print_gate_summary(result)

    if "report_html" in result and args.output:
        print(f"\nReport written to {args.output}")

    sarif_path = getattr(args, "report_sarif", None)
    if sarif_path:
        _write_sarif_output(result, sarif_path)

    if suggest_patch:
        _print_patches(result)


def cmd_check_commits(args: argparse.Namespace) -> int:
    """Run ImpactGuard pipeline comparing two git commits."""
    from .pipeline import run_pipeline_git

    suggest_patch: bool = getattr(args, "suggest_patch", False)
    strict_extraction: bool = getattr(args, "strict_extraction", False)
    enforce_gate: bool = getattr(args, "enforce_gate", False)
    block_unknown: bool | None = getattr(args, "block_unknown", None) or None
    require_runtime: bool = getattr(args, "require_runtime", False)
    generate_fixes: bool = not bool(getattr(args, "no_generate_fixes", False))
    apply_safe_fixes: bool = bool(getattr(args, "apply_safe_fixes", False))
    use_call_graph: bool = getattr(args, "use_call_graph", False)
    conservative: bool = getattr(args, "conservative", False)

    max_parse_failures: int = getattr(args, "max_parse_failures", 0)
    max_skipped_files: int = getattr(args, "max_skipped_files", 0)
    max_call_extraction_failures: int = getattr(args, "max_call_extraction_failures", 0)
    max_runtime_data_issues: int = getattr(args, "max_runtime_data_issues", 0)

    if getattr(args, "strict_analysis", False):
        strict_extraction = True
        enforce_gate = True
        max_parse_failures = 0
        max_skipped_files = 0
        max_call_extraction_failures = 0
        max_runtime_data_issues = 0

    print(f"Checking impact: {args.old_ref} \u2192 {args.new_ref}")

    try:
        result = run_pipeline_git(
            old_ref=args.old_ref,
            new_ref=args.new_ref,
            files=args.files if hasattr(args, "files") else None,
            runtime_path=args.runtime,
            output_path=args.output,
            suggest_patch=suggest_patch,
            generate_fixes=generate_fixes,
            apply_safe_fixes=apply_safe_fixes,
            strict_extraction=strict_extraction,
            max_parse_failures=max_parse_failures,
            max_skipped_files=max_skipped_files,
            max_call_extraction_failures=max_call_extraction_failures,
            max_runtime_data_issues=max_runtime_data_issues,
            block_unknown=block_unknown,
            require_runtime=require_runtime,
            use_call_graph=use_call_graph,
            conservative=conservative,
        )

        _print_check_result(result, args, suggest_patch)

        sarif_path = getattr(args, "report_sarif", None)
        if sarif_path:
            _write_sarif_output(result, sarif_path)

        if enforce_gate:
            gate = result.get("gate", {})
            return 1 if gate.get("blocked", False) else 0
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def _run_diff_pipe(
    args: argparse.Namespace,
    suggest_patch: bool,
    show_patch: bool,
    strict_extraction: bool,
    use_call_graph: bool,
    conservative: bool,
) -> dict[str, Any] | None:
    from .pipeline import run_pipeline_diff_content

    if sys.stdin.isatty():
        print("Error: --pipe requires data on stdin", file=sys.stderr)
        return None
    try:
        diff_text = sys.stdin.read()
    except UnicodeDecodeError:
        print(
            "Error: --pipe received binary data; expected text diff.", file=sys.stderr
        )
        return None
    print("Analyzing diff from stdin")
    try:
        return run_pipeline_diff_content(
            diff_text=diff_text,
            runtime_path=getattr(args, "runtime", None),
            output_dir=getattr(args, "output", None),
            suggest_patch=suggest_patch,
            show_patch=show_patch,
            generate_fixes=not bool(getattr(args, "no_generate_fixes", False)),
            apply_safe_fixes=bool(getattr(args, "apply_safe_fixes", False)),
            strict_extraction=strict_extraction,
            use_call_graph=use_call_graph,
            conservative=conservative,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


def _run_diff_file(
    args: argparse.Namespace, strict_extraction: bool, use_call_graph: bool, conservative: bool,
) -> dict[str, Any] | None:
    from .pipeline import run_pipeline_diff

    diff_path = getattr(args, "diff", None)
    if not diff_path:
        print("Error: provide a diff path or use --pipe", file=sys.stderr)
        return None
    print(f"Analyzing diff: {diff_path}")
    try:
        return run_pipeline_diff(
            diff_path=diff_path,
            runtime_path=getattr(args, "runtime", None),
            output_dir=getattr(args, "output", None),
            suggest_patch=getattr(args, "suggest_patch", False),
            generate_fixes=not bool(getattr(args, "no_generate_fixes", False)),
            apply_safe_fixes=bool(getattr(args, "apply_safe_fixes", False)),
            strict_extraction=strict_extraction,
            use_call_graph=use_call_graph,
            conservative=conservative,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


def _print_diff_result(
    result: dict[str, Any], args: argparse.Namespace, suggest_patch: bool
) -> None:
    comparison = result.get("comparison", {})
    print("\n=== Comparison ===")
    print(f"Breaking changes: {len(comparison.get('breaking', []))}")
    print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
    _print_breaking_details(comparison)

    if "semver" in result:
        sv = result["semver"]
        print("\n=== Semver Recommendation ===")
        print(f"Bump: {sv.get('bump', 'patch').upper()}  \u2014 {sv.get('reason', '')}")

    _print_risk_analysis(result)

    if "analysis_status" in result:
        status = result["analysis_status"]
        counters = status.get("counters", {})
        print("\n=== Analysis Status ===")
        print(f"Status: {status.get('status', 'unknown').upper()}")
        print(
            "Counters: "
            f"parse_failures={counters.get('parse_failures', 0)}, "
            f"skipped_files={counters.get('skipped_files', 0)}, "
            f"fallback_used={counters.get('fallback_used', 0)}"
        )

    output = getattr(args, "output", None)
    if output and "report_html" in result:
        from pathlib import Path as _Path

        output_path = _Path(output)
        report_path = (
            str(output_path / "impact_report.html") if output_path.is_dir() else output
        )
        with open(report_path, "w") as f:
            f.write(result["report_html"])
        print(f"\nReport written to {report_path}")

    sarif_path = getattr(args, "report_sarif", None)
    if sarif_path:
        _write_sarif_output(result, sarif_path)

    if suggest_patch and "patches" in result:
        patches = result["patches"]
        if patches:
            print(f"\n=== Generated Patches ({len(patches)}) ===")
            for func_name, patch_info in patches.items():
                print(f"  - {func_name}: {patch_info.get('type', 'unknown')} patch")
                print(f"    File: {patch_info.get('file', '')}")


def cmd_check_diff(args: argparse.Namespace) -> int:
    """Run ImpactGuard pipeline on a unified diff / patch file."""
    suggest_patch: bool = getattr(args, "suggest_patch", False)
    show_patch: bool = getattr(args, "show_patch", False)
    strict_extraction: bool = getattr(args, "strict_extraction", False)
    use_call_graph: bool = getattr(args, "use_call_graph", False)
    conservative: bool = getattr(args, "conservative", False)

    if getattr(args, "pipe", False):
        result = _run_diff_pipe(args, suggest_patch, show_patch, strict_extraction, use_call_graph, conservative)
    else:
        result = _run_diff_file(args, strict_extraction, use_call_graph, conservative)

    if result is None:
        return 1

    _print_diff_result(result, args, suggest_patch)
    comparison = result.get("comparison", {})
    return 1 if comparison.get("breaking") else 0


def cmd_check_commit(args: argparse.Namespace) -> int:
    """Run ImpactGuard pipeline on a single git commit vs its parent."""
    from .pipeline import run_pipeline_commit

    suggest_patch: bool = getattr(args, "suggest_patch", False)
    generate_fixes: bool = not bool(getattr(args, "no_generate_fixes", False))
    apply_safe_fixes: bool = bool(getattr(args, "apply_safe_fixes", False))
    strict_extraction: bool = getattr(args, "strict_extraction", False)
    use_call_graph: bool = getattr(args, "use_call_graph", False)
    conservative: bool = getattr(args, "conservative", False)
    print(f"Analyzing commit: {args.commit_ref}")

    try:
        result = run_pipeline_commit(
            commit_ref=args.commit_ref,
            files=getattr(args, "files", None),
            runtime_path=getattr(args, "runtime", None),
            output_path=getattr(args, "output", None),
            suggest_patch=suggest_patch,
            generate_fixes=generate_fixes,
            apply_safe_fixes=apply_safe_fixes,
            strict_extraction=strict_extraction,
            use_call_graph=use_call_graph,
            conservative=conservative,
        )
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print("\n=== Comparison ===")
    comparison = result.get("comparison", {})
    print(f"Breaking changes: {len(comparison.get('breaking', []))}")
    print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
    _print_breaking_details(comparison)

    if "semver" in result:
        sv = result["semver"]
        print("\n=== Semver Recommendation ===")
        print(f"Bump: {sv.get('bump', 'patch').upper()}  — {sv.get('reason', '')}")

    _print_risk_analysis(result)

    if "analysis_status" in result:
        status = result["analysis_status"]
        counters = status.get("counters", {})
        print("\n=== Analysis Status ===")
        print(f"Status: {status.get('status', 'unknown').upper()}")
        print(
            "Counters: "
            f"parse_failures={counters.get('parse_failures', 0)}, "
            f"skipped_files={counters.get('skipped_files', 0)}, "
            f"fallback_used={counters.get('fallback_used', 0)}"
        )

    if "report_html" in result and args.output:
        print(f"\nReport written to {args.output}")

    sarif_path = getattr(args, "report_sarif", None)
    if sarif_path:
        _write_sarif_output(result, sarif_path)

    if suggest_patch and "patches" in result:
        patches = result["patches"]
        if patches:
            print(f"\n=== Generated Patches ({len(patches)}) ===")
            for func_name, patch_info in patches.items():
                print(f"  - {func_name}: {patch_info.get('type', 'unknown')} patch")
                print(f"    File: {patch_info.get('file', '')}")

    return 1 if comparison.get("breaking") else 0


def _hook_install_flags(args: argparse.Namespace) -> tuple[bool, bool, bool]:
    """Return booleans for pre/post/workflow installation."""
    install_pre = (
        args.pre or args.both or (not args.pre and not args.post and not args.both)
    )
    install_post = (
        args.post or args.both or (not args.pre and not args.post and not args.both)
    )
    install_workflow = getattr(args, "install_github_workflow", False)
    return install_pre, install_post, install_workflow


def _load_precommit_config(config_path: Path, yaml: Any) -> dict[str, Any]:
    """Load existing pre-commit YAML, or initialize an empty config."""
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _ensure_local_repo_entry(config: dict[str, Any]) -> dict[str, Any]:
    """Ensure the pre-commit config has a local repo entry."""
    repos = config.setdefault("repos", [])
    for repo in repos:
        if repo.get("repo") == "local":
            return repo
    local_repo: dict[str, Any] = {"repo": "local", "hooks": []}
    repos.append(local_repo)
    return local_repo


def _write_precommit_yaml(
    config_path: Path, impactguard_hooks: list[dict[str, Any]], yaml: Any
) -> None:
    """Update the YAML pre-commit config with ImpactGuard hooks."""
    config = _load_precommit_config(config_path, yaml)
    local_repo = _ensure_local_repo_entry(config)
    existing_hooks = local_repo.get("hooks", [])
    local_repo["hooks"] = [
        hook
        for hook in existing_hooks
        if hook.get("id") not in ["impactguard-check", "impactguard-post-commit"]
    ]
    local_repo["hooks"].extend(impactguard_hooks)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"Updated .pre-commit-config.yaml: {config_path}")


def _write_precommit_text(
    config_path: Path, impactguard_hooks: list[dict[str, Any]]
) -> None:
    """Write a minimal text fallback pre-commit config."""
    lines = ["repos:", "  - repo: local", "    hooks:"]
    for hook in impactguard_hooks:
        lines.append(f"      - id: {hook['id']}")
        lines.append(f'        name: "{hook["name"]}"')
        lines.append(f"        entry: {hook['entry']}")
        lines.append(f"        language: {hook['language']}")
        if "files" in hook:
            lines.append(f"        files: '{hook['files']}'")
        if "always_run" in hook:
            lines.append(f"        always_run: {hook['always_run']}")
        lines.append(f"        stages: {hook['stages']}")
    config_path.write_text("\n".join(lines) + "\n")
    print(f"Created .pre-commit-config.yaml: {config_path}")


def _install_precommit_hooks(
    repo_path: Path, install_pre: bool, install_post: bool
) -> int:
    """Install pre-commit hooks into the target repository."""
    import subprocess

    try:
        commands = []
        if install_pre:
            commands.append(
                (
                    ["pre-commit", "install"],
                    "Installed pre-commit hook via pre-commit package",
                    "Warning: pre-commit install failed",
                )
            )
        if install_post:
            commands.append(
                (
                    ["pre-commit", "install", "--hook-type", "post-commit"],
                    "Installed post-commit hook via pre-commit package",
                    "Warning: pre-commit install --hook-type post-commit failed",
                )
            )

        for command, success_msg, failure_prefix in commands:
            result = subprocess.run(
                command,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(success_msg)
            else:
                print(f"{failure_prefix}: {result.stderr}")
    except FileNotFoundError:
        print(
            "Error: pre-commit package not found. Install it with: pip install pre-commit"
        )
        return 1
    except Exception as e:
        print(f"Error installing hooks: {e}")
        return 1
    return 0


def _maybe_install_workflow(repo_path: Path, install_workflow: bool) -> None:
    """Create the optional GitHub Actions workflow file."""
    if not install_workflow:
        return

    workflow_dir = repo_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "impactguard.yml"
    workflow_content = """name: ImpactGuard

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  impactguard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install ImpactGuard
        run: pip install impactguard[all]
      - name: Run ImpactGuard
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            impactguard check-commits "${{ github.event.pull_request.base.sha }}" "${{ github.event.pull_request.head.sha }}"
          else
            impactguard check-commit HEAD
          fi
"""
    workflow_path.write_text(workflow_content)
    print(f"Created GitHub workflow: {workflow_path}")


def cmd_install_hooks(args: argparse.Namespace) -> int:
    """Install git hooks for ImpactGuard using pre-commit package."""
    from pathlib import Path

    repo_path = Path(args.repo_path).resolve()
    git_dir = repo_path / ".git"

    if not git_dir.exists():
        print(f"Error: Not a git repository: {repo_path}")
        return 1

    install_pre, install_post, install_workflow = _hook_install_flags(args)

    # Ensure .pre-commit-config.yaml exists with full pipeline (use YAML formatter)
    config_path = repo_path / ".pre-commit-config.yaml"
    try:
        import yaml

        yaml_available = True
    except ImportError:
        print("Warning: pyyaml not installed, using basic YAML generation")
        yaml_available = False

    impactguard_hooks: list[dict[str, Any]] = []
    if install_pre:
        impactguard_hooks.append(
            {
                "id": "impactguard-check",
                "name": "ImpactGuard - Full Pipeline Check",
                "entry": "impactguard-check-staged",
                "language": "system",
                "files": r"\.py$",
                "stages": ["pre-commit"],
            }
        )
    if install_post:
        impactguard_hooks.append(
            {
                "id": "impactguard-post-commit",
                "name": "ImpactGuard - Post-Commit Analysis",
                "entry": "impactguard-post-commit-hook",
                "language": "system",
                "always_run": True,
                "stages": ["post-commit"],
            }
        )

    if yaml_available:
        _write_precommit_yaml(config_path, impactguard_hooks, yaml)
    else:
        _write_precommit_text(config_path, impactguard_hooks)

    # Install hooks using pre-commit package
    install_result = _install_precommit_hooks(repo_path, install_pre, install_post)
    if install_result != 0:
        return install_result

    _maybe_install_workflow(repo_path, install_workflow)

    print("\nHooks installed successfully using pre-commit package")
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
        with open(args.report) as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error reading report: {e}", file=sys.stderr)
        return 1

    if not isinstance(report, list):
        print(
            f"Error: report file must contain a JSON array, got {type(report).__name__}",
            file=sys.stderr,
        )
        return 1

    all_suggestions: list[str] = []
    for item in report:
        if not isinstance(item, dict):
            continue
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

    from .cst_patch import patch_call, patch_function

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

    apply: bool = getattr(args, "apply", False)
    if apply:
        Path(args.file).write_text(result or "")
        print(f"Patch applied to {args.file}")
    elif args.output:
        Path(args.output).write_text(result or "")
    else:
        print(result)

    return 0


def _baseline_save(args: argparse.Namespace, baseline_path: str | None) -> int:
    from .baseline import save_baseline

    files = getattr(args, "files", None) or []
    if not files:
        import glob as _glob

        files = list(_glob.glob("**/*.py", recursive=True))
        if not files:
            print("Error: No Python files found", file=sys.stderr)
            return 1

    import datetime

    metadata = {
        "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "files_count": len(files),
    }
    saved = save_baseline(files, baseline_path, metadata)
    print(f"Baseline saved: {saved} ({len(files)} file(s))")
    return 0


def _baseline_status(_args: argparse.Namespace, baseline_path: str | None) -> int:
    from .baseline import DEFAULT_BASELINE_PATH, baseline_exists, load_baseline

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


def _baseline_compare(args: argparse.Namespace, baseline_path: str | None) -> int:
    from .baseline import compare_with_baseline

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
    print(
        f"Semver recommendation: {semver.get('bump', 'patch').upper()} \u2014 {semver.get('reason', '')}"
    )

    for item in comparison.get("breaking", []):
        print(f"  \u26a0 {item}")

    output = getattr(args, "output", None)
    if output:
        import json

        with open(output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nResult written to {output}")

    return 1 if comparison.get("breaking") else 0


_SUBCOMMANDS = {
    "save": _baseline_save,
    "status": _baseline_status,
    "compare": _baseline_compare,
}


def cmd_baseline(args: argparse.Namespace) -> int:
    """Manage ImpactGuard baselines."""
    subcommand: str = args.baseline_cmd or "status"
    baseline_path: str | None = getattr(args, "baseline_path", None)

    handler = _SUBCOMMANDS.get(subcommand)
    if handler is None:
        print(f"Unknown baseline subcommand: {subcommand}", file=sys.stderr)
        return 1
    return handler(args, baseline_path)


def cmd_semver(args: argparse.Namespace) -> int:
    """Suggest a semver bump from two signature snapshots."""
    from .compare_signatures import compare
    from .semver import format_semver_recommendation

    # Use getattr for backward compatibility (tests may not have json attribute)
    use_json = getattr(args, "json", False)

    if use_json:
        # JSON mode: compare two JSON files directly
        try:
            result = compare(args.old, args.new)
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        # Source mode: extract signatures from source files, then compare
        from .languages.lib.registry import get_extractor

        def _extract_file(file_path: str) -> list[dict[str, Any]]:
            """Extract signatures from a single source file."""
            extractor = get_extractor(file_path)
            if extractor is None:
                print(
                    f"Error: No extractor found for file '{file_path}'",
                    file=sys.stderr,
                )
                return []
            method = getattr(extractor, "extract_signatures", None)
            if method is None:
                print(
                    f"Error: Extractor for '{file_path}' has no extract_signatures method",
                    file=sys.stderr,
                )
                return []
            return method([file_path])

        old_sigs = _extract_file(args.old)
        new_sigs = _extract_file(args.new)

        if not old_sigs:
            print(
                f"Error: Failed to extract signatures from '{args.old}'",
                file=sys.stderr,
            )
            return 1
        if not new_sigs:
            print(
                f"Error: Failed to extract signatures from '{args.new}'",
                file=sys.stderr,
            )
            return 1

        result = compare(old_sigs, new_sigs)

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


def cmd_report_sarif(args: argparse.Namespace) -> int:
    """Generate a SARIF v2.1.0 log from a risk report JSON."""
    from .sarif import generate_sarif_from_file

    output: str | None = getattr(args, "output", None)
    try:
        sarif = generate_sarif_from_file(args.report, output_path=output)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not output:
        print(json.dumps(sarif, indent=2))
    else:
        print(f"SARIF log written to {output}")
    return 0


def cmd_report_markdown(args: argparse.Namespace) -> int:
    """Generate a markdown PR-comment summary from a risk report JSON."""
    from .generate_report import generate_markdown_from_file

    output: str | None = getattr(args, "output", None)
    try:
        md = generate_markdown_from_file(args.report, output_path=output)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not output:
        print(md)
    else:
        print(f"Markdown report written to {output}")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    """Manage patch-outcome feedback for confidence calibration."""
    from .feedback import (
        apply_weights_to_config,
        compute_calibrated_weights,
        compute_data_needs,
        get_stats,
        load_outcomes,
        record_outcome,
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
            needs = compute_data_needs(outcomes)
            if needs:
                print("Not enough data for calibration (need ≥ 5 outcomes per category):")
                for ct, needed in sorted(needs.items()):
                    print(f"  {ct}: {needed} more outcome(s) needed")
            else:
                print("No feedback data recorded yet.")
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


def _collect_python_files() -> list[str]:
    """Collect Python source files from the current working tree."""
    import glob as _glob

    return list(_glob.glob("**/*.py", recursive=True))


def _require_python_files(files: list[str] | None) -> list[str]:
    """Return provided files or discover Python files, exiting on empty input."""
    discovered = files or _collect_python_files()
    if discovered:
        return discovered
    print("Error: No Python files found", file=sys.stderr)
    return []


def _baseline_metadata(files: list[str]) -> dict[str, Any]:
    """Build baseline metadata for save operations."""
    import datetime

    return {
        "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "files_count": len(files),
    }


def _write_json_output(path: str | None, payload: Any) -> None:
    """Write optional JSON output for CLI commands."""
    if not path:
        return
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nResult written to {path}")


def _list_tagged_baselines(history_path: str | None, list_baselines: Any) -> int:
    """Handle the tagged baseline list subcommand."""
    entries = list_baselines(history_path)
    if not entries:
        print("No tagged baselines stored yet.")
    for entry in entries:
        meta = entry.get("metadata") or {}
        saved_at = meta.get("saved_at", "")
        print(
            f"  {entry['tag']:20s}  {entry['signature_count']:4d} signatures  {saved_at}"
        )
    return 0


def _save_tagged_baseline_cmd(
    args: argparse.Namespace,
    history_path: str | None,
    save_tagged_baseline: Any,
) -> int:
    """Handle the tagged baseline save subcommand."""
    files = _require_python_files(getattr(args, "files", None) or [])
    if not files:
        return 1

    try:
        saved = save_tagged_baseline(
            args.tag, files, history_path, _baseline_metadata(files)
        )
        print(f"Tagged baseline '{args.tag}' saved to {saved} ({len(files)} file(s))")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def _compare_tagged_baseline_cmd(
    args: argparse.Namespace,
    history_path: str | None,
    compare_with_tagged_baseline: Any,
) -> int:
    """Handle the tagged baseline compare subcommand."""
    files = _require_python_files(getattr(args, "files", None) or [])
    if not files:
        return 1

    try:
        result = compare_with_tagged_baseline(args.tag_from, files, history_path)
    except (FileNotFoundError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    comparison = result["comparison"]
    semver = result["semver"]
    print(f"Comparing against baseline tag '{args.tag_from}':")
    print(f"  Breaking changes:     {len(comparison.get('breaking', []))}")
    print(f"  Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
    print(f"  Semver recommendation: {semver.get('bump', 'patch').upper()}")
    for item in comparison.get("breaking", []):
        print(f"  ⚠ {item}")

    _write_json_output(getattr(args, "output", None), result)
    return 1 if comparison.get("breaking") else 0


def cmd_baseline_tagged(args: argparse.Namespace) -> int:
    """Handle tagged baseline sub-subcommands: save --tag, list, compare --from."""
    from .baseline import (
        compare_with_tagged_baseline,
        delete_tagged_baseline,
        list_baselines,
        save_tagged_baseline,
    )

    subcmd: str = getattr(args, "tagged_cmd", "") or "list"
    history_path: str | None = getattr(args, "history_path", None)

    if subcmd == "list":
        return _list_tagged_baselines(history_path, list_baselines)

    if subcmd == "save":
        return _save_tagged_baseline_cmd(args, history_path, save_tagged_baseline)

    if subcmd == "compare":
        return _compare_tagged_baseline_cmd(
            args, history_path, compare_with_tagged_baseline
        )

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


def cmd_kpi(args: argparse.Namespace) -> int:
    """Compute and display KPI dashboard from a risk report JSON."""
    from .feedback import load_outcomes
    from .kpi import compute_kpis, format_kpi_text

    try:
        with open(args.report) as f:
            report_data = json.load(f)
    except OSError as exc:
        print(f"Error reading report: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Error parsing report JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(report_data, list):
        print(
            f"Error: report file must contain a JSON array, got {type(report_data).__name__}",
            file=sys.stderr,
        )
        return 1

    feedback_outcomes = None
    feedback_path: str | None = getattr(args, "feedback_path", None)
    if feedback_path:
        feedback_outcomes = load_outcomes(feedback_path)

    kpis = compute_kpis(report_data, feedback_outcomes=feedback_outcomes)

    output: str | None = getattr(args, "output", None)
    if output:
        with open(output, "w") as f:
            json.dump(kpis, f, indent=2)
        print(f"KPIs written to {output}")
    else:
        print(format_kpi_text(kpis))

    return 0


def cmd_analyze_behavior(args: argparse.Namespace) -> int:
    """Detect semantic/behavioral changes between two Python source files.

    Compares function bodies to surface behavioral shifts that are invisible
    to signature-level diffing: async/sync transitions, generator changes,
    exception contract changes, side-effect additions/removals, return-value
    semantics, and docstring contract changes.
    """
    from .semantic_analysis import analyze_behavior, compare_behavior

    base_path: str | None = getattr(args, "base_path", None)
    old_files = [args.old] if isinstance(args.old, str) else list(args.old)
    new_files = [args.new] if isinstance(args.new, str) else list(args.new)

    try:
        old_traits = analyze_behavior(old_files, base_path=base_path)
        new_traits = analyze_behavior(new_files, base_path=base_path)
    except Exception as exc:
        print(f"Error during behavior analysis: {exc}", file=sys.stderr)
        return 1

    result = compare_behavior(old_traits, new_traits)

    breaking = result.get("semantic_breaking", [])
    nonbreaking = result.get("semantic_nonbreaking", [])

    print(f"Semantic breaking changes:     {len(breaking)}")
    print(f"Semantic non-breaking changes: {len(nonbreaking)}")

    for item in breaking:
        print(f"  ⚠ {item}")
    for item in nonbreaking:
        print(f"  ℹ {item}")

    output = getattr(args, "output", None)
    if output:
        with open(output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nSemantic diff written to {output}")

    return 1 if breaking else 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    """Validate the impactguard.toml configuration file."""
    from .config import validate_config

    config_path: str | None = getattr(args, "config_path", None)
    issues = validate_config(config_path)

    if not issues:
        path_hint = config_path or "impactguard.toml"
        print(f"✓ Configuration valid ({path_hint})")
        return 0

    has_errors = False
    for issue in issues:
        if issue.startswith("ERROR:"):
            print(f"✗ {issue[6:].strip()}", file=sys.stderr)
            has_errors = True
        elif issue.startswith("WARN:"):
            print(f"⚠ {issue[5:].strip()}")
        else:
            # INFO: or plain
            print(f"ℹ {issue.removeprefix('INFO:').strip()}")

    if not has_errors:
        print("✓ Configuration valid (warnings only)")
    return 1 if has_errors else 0


def main() -> int:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="impactguard",
        description="ImpactGuard - API impact analyzer for Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--log-level",
        default=None,
        metavar="LEVEL",
        help=(
            "Logging level for the impactguard logger "
            "(DEBUG, INFO, WARNING, ERROR, CRITICAL). "
            "Defaults to the value in impactguard.toml [impactguard.logging] level, "
            "or WARNING when no config is found."
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional log file path (appended). Defaults to stderr only.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # extract subcommand
    extract_parser = subparsers.add_parser(
        "extract", help="Extract function signatures from source files"
    )
    extract_parser.add_argument(
        "files",
        nargs="*",
        help="Source files to analyze (Python, TypeScript, …)",
    )
    extract_parser.add_argument(
        "--language",
        "-l",
        help="Force a specific language (e.g. python, typescript); "
        "auto-detected from extension when omitted",
    )
    extract_parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Treat parse errors as fatal instead of skipping the file. "
        "Recommended for CI to ensure broken files are never silently ignored.",
    )
    extract_parser.add_argument(
        "--incremental",
        action="store_true",
        default=False,
        help="Only extract signatures for files whose content has changed since "
        "the last call graph build/sync. Requires a pre-existing call graph DB. "
        "Fall back to full extraction when no DB is found.",
    )
    extract_parser.set_defaults(func=cmd_extract)

    # compare subcommand
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare signature snapshots or source files",
        description=(
            "Compare two signature snapshots (JSON files) or two source files.  "
            "By default, treat OLD and NEW as source files and extract signatures "
            "automatically.  Use --json to compare pre-extracted JSON files."
        ),
    )
    compare_parser.add_argument("old", help="Old file (source file or JSON)")
    compare_parser.add_argument("new", help="New file (source file or JSON)")
    compare_parser.add_argument(
        "--json",
        action="store_true",
        help="Treat OLD and NEW as JSON signature files (default: extract from source files)",
    )
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
    risk_parser.add_argument(
        "diff", nargs="?", help="Diff text file (omit with --pipe)"
    )
    risk_parser.add_argument("runtime", help="Runtime data JSON file")
    risk_parser.add_argument("output", help="Output report JSON file")
    risk_parser.add_argument(
        "--pipe",
        action="store_true",
        help="Read diff from stdin instead of a file (e.g. diff A B | impactguard risk --pipe ...)",
    )
    risk_parser.add_argument(
        "--lambda-factor",
        dest="lambda_factor",
        type=float,
        default=1.0,
        metavar="FACTOR",
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
    enforce_parser = subparsers.add_parser(
        "enforce", help="Enforce gate - block on HIGH risk"
    )
    enforce_parser.add_argument(
        "diff", nargs="?", help="Diff text file (omit with --pipe)"
    )
    enforce_parser.add_argument("runtime", help="Runtime data JSON file")
    enforce_parser.add_argument("-o", "--output", help="Output report JSON file")
    enforce_parser.add_argument(
        "--block-unknown",
        action="store_true",
        help="Treat UNKNOWN risk as a blocking condition (same as HIGH)",
    )
    enforce_parser.add_argument(
        "--pipe",
        action="store_true",
        help="Read diff from stdin instead of a file (e.g. diff A B | impactguard enforce --pipe ...)",
    )
    enforce_parser.add_argument(
        "--lambda-factor",
        dest="lambda_factor",
        type=float,
        default=1.0,
        metavar="FACTOR",
        help="Sensitivity multiplier (default: 1.0). >1 increases sensitivity; <1 decreases it.",
    )
    enforce_parser.set_defaults(func=cmd_enforce)

    # suggest subcommand
    suggest_parser = subparsers.add_parser(
        "suggest", help="Generate fix suggestions from risk report"
    )
    suggest_parser.add_argument("report", help="Risk report JSON file")
    suggest_parser.add_argument(
        "-o", "--output", help="Output JSON file for suggestions"
    )
    suggest_parser.set_defaults(func=cmd_suggest)

    # patch subcommand
    patch_parser = subparsers.add_parser("patch", help="Generate CST-based patches")
    patch_parser.add_argument("file", help="Python source file to patch")
    patch_parser.add_argument("func_name", help="Function name to patch")
    patch_parser.add_argument("param_name", help="Parameter name to patch")
    patch_parser.add_argument(
        "--type",
        dest="patch_type",
        choices=["function", "call"],
        default="function",
        help="Patch type: 'function' adds default, 'call' fixes call site",
    )
    patch_parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    patch_parser.add_argument(
        "--apply",
        "-a",
        action="store_true",
        default=False,
        help="Write the patched content back to the original source file in-place",
    )
    patch_parser.set_defaults(func=cmd_patch)

    # extract-calls subcommand
    extract_calls_parser = subparsers.add_parser(
        "extract-calls", help="Extract call sites from source files"
    )
    extract_calls_parser.add_argument(
        "files",
        nargs="*",
        help="Source files to analyze (Python, TypeScript, …)",
    )
    extract_calls_parser.add_argument(
        "--language",
        "-l",
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
    check_parser.add_argument("runtime", nargs="?", help="Runtime data JSON (optional)")
    check_parser.add_argument(
        "output", nargs="?", default="impact_report.html", help="Output HTML report"
    )
    check_parser.add_argument(
        "--report-sarif",
        nargs="?",
        const="impact_report.sarif",
        metavar="FILE",
        help="Generate SARIF v2.1.0 log (default: impact_report.sarif)",
    )
    check_parser.add_argument(
        "--watch",
        action="store_true",
        help="Re-run automatically when source files change",
    )
    check_parser.add_argument(
        "--suggest-patch",
        action="store_true",
        dest="suggest_patch",
        help="Generate patches for suggested fixes",
    )
    check_parser.add_argument(
        "--show-patch",
        action="store_true",
        dest="show_patch",
        help="Show how old file would look if patched",
    )
    check_parser.add_argument(
        "--no-generate-fixes",
        action="store_true",
        default=False,
        help="Disable internal fix-candidate generation in pipeline output.",
    )
    check_parser.add_argument(
        "--apply-safe-fixes",
        action="store_true",
        default=False,
        help="Apply high-confidence CST fixes automatically (conservative mode).",
    )
    check_parser.add_argument(
        "--use-call-graph",
        action="store_true",
        default=False,
        help="Enable persistent call graph (pre-indexed call extraction)",
    )
    check_parser.add_argument(
        "--conservative",
        action="store_true",
        default=False,
        help="Flag changes touching uncalled functions/symbols as potential impact (dynamic dispatch blind spot).",
    )
    check_parser.set_defaults(func=cmd_check)

    # check-diff subcommand (unified diff / patch file)
    check_diff_parser = subparsers.add_parser(
        "check-diff", help="Run full pipeline on a unified diff / patch file"
    )
    check_diff_parser.add_argument(
        "diff", nargs="?", help="Path to unified diff / patch file (omit with --pipe)"
    )
    check_diff_parser.add_argument("--runtime", help="Runtime data JSON (optional)")
    check_diff_parser.add_argument(
        "-o", "--output", help="Output directory or HTML report path"
    )
    check_diff_parser.add_argument(
        "--pipe",
        action="store_true",
        help="Read diff from stdin instead of a file (e.g. diff A B | impactguard check-diff --pipe)",
    )
    check_diff_parser.add_argument(
        "--suggest-patch",
        action="store_true",
        dest="suggest_patch",
        help="Generate patches for suggested fixes",
    )
    check_diff_parser.add_argument(
        "--show-patch",
        action="store_true",
        dest="show_patch",
        help="Show how old file would look if patched",
    )
    check_diff_parser.add_argument(
        "--no-generate-fixes",
        action="store_true",
        default=False,
        help="Disable internal fix-candidate generation in pipeline output.",
    )
    check_diff_parser.add_argument(
        "--apply-safe-fixes",
        action="store_true",
        default=False,
        help="Apply high-confidence CST fixes automatically (conservative mode).",
    )
    check_diff_parser.add_argument(
        "--strict-extraction",
        action="store_true",
        default=False,
        help="Treat signature extraction failures as fatal when supported by the extractor.",
    )
    check_diff_parser.add_argument(
        "--report-sarif",
        metavar="PATH",
        help="Write SARIF v2.1.0 report to PATH",
    )
    check_diff_parser.add_argument(
        "--use-call-graph",
        action="store_true",
        default=False,
        help="Enable persistent call graph (pre-indexed call extraction)",
    )
    check_diff_parser.add_argument(
        "--conservative",
        action="store_true",
        default=False,
        help="Flag changes touching uncalled functions/symbols as potential impact (dynamic dispatch blind spot).",
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
    check_commit_parser.add_argument("--runtime", help="Runtime data JSON (optional)")
    check_commit_parser.add_argument(
        "-o", "--output", help="Output path for HTML report"
    )
    check_commit_parser.add_argument(
        "--suggest-patch",
        action="store_true",
        dest="suggest_patch",
        help="Generate patches for suggested fixes",
    )
    check_commit_parser.add_argument(
        "--show-patch",
        action="store_true",
        dest="show_patch",
        help="Show how old file would look if patched",
    )
    check_commit_parser.add_argument(
        "--no-generate-fixes",
        action="store_true",
        default=False,
        help="Disable internal fix-candidate generation in pipeline output.",
    )
    check_commit_parser.add_argument(
        "--apply-safe-fixes",
        action="store_true",
        default=False,
        help="Apply high-confidence CST fixes automatically (conservative mode).",
    )
    check_commit_parser.add_argument(
        "--strict-extraction",
        action="store_true",
        default=False,
        help="Treat signature extraction failures as fatal when supported by the extractor.",
    )
    check_commit_parser.add_argument(
        "--report-sarif",
        metavar="PATH",
        help="Write SARIF v2.1.0 report to PATH",
    )
    check_commit_parser.add_argument(
        "--use-call-graph",
        action="store_true",
        default=False,
        help="Enable persistent call graph (pre-indexed call extraction)",
    )
    check_commit_parser.add_argument(
        "--conservative",
        action="store_true",
        default=False,
        help="Flag changes touching uncalled functions/symbols as potential impact (dynamic dispatch blind spot).",
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
    check_commits_parser.add_argument("--runtime", help="Runtime data JSON (optional)")
    check_commits_parser.add_argument(
        "-o", "--output", help="Output path for HTML report"
    )
    check_commits_parser.add_argument(
        "--suggest-patch",
        action="store_true",
        dest="suggest_patch",
        help="Generate patches for suggested fixes",
    )
    check_commits_parser.add_argument(
        "--show-patch",
        action="store_true",
        dest="show_patch",
        help="Show how old file would look if patched",
    )
    check_commits_parser.add_argument(
        "--no-generate-fixes",
        action="store_true",
        default=False,
        help="Disable internal fix-candidate generation in pipeline output.",
    )
    check_commits_parser.add_argument(
        "--apply-safe-fixes",
        action="store_true",
        default=False,
        help="Apply high-confidence CST fixes automatically (conservative mode).",
    )
    check_commits_parser.add_argument(
        "--strict-extraction",
        action="store_true",
        default=False,
        help="Treat signature extraction failures as fatal when supported by the extractor.",
    )
    check_commits_parser.add_argument(
        "--enforce-gate",
        action="store_true",
        default=False,
        help="Return non-zero when gate status is blocked (single authoritative CI outcome).",
    )
    check_commits_parser.add_argument(
        "--strict-analysis",
        action="store_true",
        default=False,
        help=(
            "Enable strict CI policy: enforce gate, strict extraction, and zero-tolerance "
            "thresholds for parse/skipped/call/runtime analysis failures."
        ),
    )
    check_commits_parser.add_argument(
        "--block-unknown",
        action="store_true",
        default=False,
        help="Block on UNKNOWN-risk items in addition to HIGH-risk items.",
    )
    check_commits_parser.add_argument(
        "--require-runtime",
        action="store_true",
        default=False,
        help="Require valid runtime data; missing/invalid runtime blocks the gate.",
    )
    check_commits_parser.add_argument(
        "--max-parse-failures",
        type=int,
        default=0,
        help="Maximum allowed parse/signature extraction failures before gate blocks.",
    )
    check_commits_parser.add_argument(
        "--max-skipped-files",
        type=int,
        default=0,
        help="Maximum allowed skipped/unsupported files before gate blocks.",
    )
    check_commits_parser.add_argument(
        "--max-call-extraction-failures",
        type=int,
        default=0,
        help="Maximum allowed call extraction failures before gate blocks.",
    )
    check_commits_parser.add_argument(
        "--max-runtime-data-issues",
        type=int,
        default=0,
        help="Maximum allowed runtime data load/parse issues before gate blocks.",
    )
    check_commits_parser.add_argument(
        "--report-sarif",
        metavar="PATH",
        help="Write SARIF v2.1.0 report to PATH",
    )
    check_commits_parser.add_argument(
        "--use-call-graph",
        action="store_true",
        default=False,
        help="Enable persistent call graph (pre-indexed call extraction)",
    )
    check_commits_parser.add_argument(
        "--conservative",
        action="store_true",
        default=False,
        help="Flag changes touching uncalled functions/symbols as potential impact (dynamic dispatch blind spot).",
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
    hooks_parser.add_argument(
        "--install-github-workflow",
        action="store_true",
        help="Also create .github/workflows/impactguard.yml for CI/CD",
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
    changelog_parser.add_argument("output", nargs="?", help="Output file for changelog")
    changelog_parser.set_defaults(func=cmd_generate_changelog)

    # baseline subcommand
    baseline_parser = subparsers.add_parser(
        "baseline", help="Manage ImpactGuard signature baselines"
    )
    baseline_sub = baseline_parser.add_subparsers(
        dest="baseline_cmd", help="Baseline subcommands"
    )
    baseline_save = baseline_sub.add_parser(
        "save", help="Save current signatures as baseline"
    )
    baseline_save.add_argument(
        "files", nargs="*", help="Python files to snapshot (default: all)"
    )
    baseline_save.add_argument(
        "--path", dest="baseline_path", help="Path to baseline JSON file"
    )
    baseline_status = baseline_sub.add_parser("status", help="Show baseline info")
    baseline_status.add_argument(
        "--path", dest="baseline_path", help="Path to baseline JSON file"
    )
    baseline_compare = baseline_sub.add_parser(
        "compare", help="Compare current code against baseline"
    )
    baseline_compare.add_argument(
        "files", nargs="*", help="Python files to compare (default: all)"
    )
    baseline_compare.add_argument(
        "--path", dest="baseline_path", help="Path to baseline JSON file"
    )
    baseline_compare.add_argument(
        "-o", "--output", help="Output JSON file for comparison result"
    )
    baseline_parser.set_defaults(func=cmd_baseline)

    # semver subcommand
    semver_parser = subparsers.add_parser(
        "semver",
        help="Suggest semver bump from two signature snapshots or source files",
        description=(
            "Suggest a semantic version bump based on two signature snapshots.  "
            "By default, treat OLD and NEW as source files and extract signatures "
            "automatically.  Use --json to compare pre-extracted JSON files."
        ),
    )
    semver_parser.add_argument("old", help="Old file (source file or JSON)")
    semver_parser.add_argument("new", help="New file (source file or JSON)")
    semver_parser.add_argument(
        "--json",
        action="store_true",
        help="Treat OLD and NEW as JSON signature files (default: extract from source files)",
    )
    semver_parser.add_argument(
        "--current-version",
        dest="current_version",
        help="Current version string (e.g. 1.2.3)",
    )
    semver_parser.add_argument(
        "-o", "--output", help="Output JSON file for recommendation"
    )
    semver_parser.set_defaults(func=cmd_semver)

    # report-sarif subcommand
    report_sarif_parser = subparsers.add_parser(
        "report-sarif", help="Generate SARIF v2.1.0 log from risk report JSON"
    )
    report_sarif_parser.add_argument("report", help="Risk report JSON file")
    report_sarif_parser.add_argument(
        "-o", "--output", help="Output SARIF JSON file (default: stdout)"
    )
    report_sarif_parser.set_defaults(func=cmd_report_sarif)

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

    fb_record = feedback_sub.add_parser(
        "record", help="Record a patch acceptance/rejection"
    )
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
    hist_list.add_argument(
        "--history-path", dest="history_path", help="History JSON file path"
    )

    hist_save = history_sub.add_parser("save", help="Save a tagged baseline snapshot")
    hist_save.add_argument("tag", help="Release tag (e.g. v1.2.0)")
    hist_save.add_argument("files", nargs="*", help="Python files to snapshot")
    hist_save.add_argument(
        "--history-path", dest="history_path", help="History JSON file path"
    )

    hist_compare = history_sub.add_parser(
        "compare", help="Compare current code against a tagged baseline"
    )
    hist_compare.add_argument("tag_from", help="Tag to compare against")
    hist_compare.add_argument("files", nargs="*", help="Python files to compare")
    hist_compare.add_argument(
        "--history-path", dest="history_path", help="History JSON file path"
    )
    hist_compare.add_argument(
        "-o", "--output", help="Output JSON file for comparison result"
    )

    hist_delete = history_sub.add_parser("delete", help="Delete a tagged baseline")
    hist_delete.add_argument("tag", help="Tag to delete")
    hist_delete.add_argument(
        "--history-path", dest="history_path", help="History JSON file path"
    )

    history_parser.set_defaults(func=cmd_baseline_tagged)

    # validate-config subcommand
    validate_cfg_parser = subparsers.add_parser(
        "validate-config",
        help="Validate impactguard.toml for unknown keys and value-type errors",
    )
    validate_cfg_parser.add_argument(
        "--config-path",
        dest="config_path",
        help="Path to impactguard.toml (default: auto-discovered from cwd upward)",
    )
    validate_cfg_parser.set_defaults(func=cmd_validate_config)

    # kpi subcommand
    kpi_parser = subparsers.add_parser(
        "kpi", help="Compute KPI dashboard from a risk report JSON"
    )
    kpi_parser.add_argument("report", help="Risk report JSON file")
    kpi_parser.add_argument(
        "--feedback-path",
        dest="feedback_path",
        help="Feedback JSON file to include patch acceptance rate",
    )
    kpi_parser.add_argument(
        "-o",
        "--output",
        help="Write KPIs as JSON to this file (default: text to stdout)",
    )
    kpi_parser.set_defaults(func=cmd_kpi)

    # analyze-behavior subcommand
    behavior_parser = subparsers.add_parser(
        "analyze-behavior",
        help="Detect semantic/behavioral changes between two Python source files",
        description=(
            "Compare two Python source files to surface behavioral changes beyond "
            "signature-level diffing: async/sync transitions, generator changes, "
            "exception contracts, side effects, return semantics, and docstring "
            "contract changes."
        ),
    )
    behavior_parser.add_argument("old", help="Old Python source file to analyse")
    behavior_parser.add_argument("new", help="New Python source file to analyse")
    behavior_parser.add_argument(
        "--base-path",
        dest="base_path",
        metavar="PATH",
        help=(
            "Root directory used to make fqnames relative "
            "(same semantics as the 'extract' subcommand's base_path)"
        ),
    )
    behavior_parser.add_argument(
        "-o",
        "--output",
        help="Write semantic diff as JSON to this file (default: text to stdout)",
    )
    behavior_parser.set_defaults(func=cmd_analyze_behavior)

    if (
        len(sys.argv) > 1
        and sys.argv[1]
        not in [
            "extract",
            "compare",
            "analyze",
            "risk",
            "report",
            "report-sarif",
            "report-markdown",
            "trace",
            "check",
            "check-commits",
            "check-diff",
            "check-commit",
            "install-hooks",
            "enforce",
            "extract-calls",
            "generate-changelog",
            "suggest",
            "patch",
            "baseline",
            "semver",
            "feedback",
            "history",
            "validate-config",
            "kpi",
            "analyze-behavior",
        ]
        and not sys.argv[1].startswith("-")
    ):
        # Assume pipeline mode: impactguard old/ new/ [runtime] [output]
        sys.argv.insert(1, "check")

    args = parser.parse_args()

    # Configure the impactguard logger hierarchy using our centralised helper.
    # Precedence: CLI > config file > built-in defaults.
    from ._logging import _logging_config_from_config, configure_logging, get_logger

    _log_cfg = _logging_config_from_config()
    log_level: str = args.log_level or _log_cfg["level"]
    log_format: str = _log_cfg["format"]
    log_file: str | None = args.log_file or _log_cfg["log_file"] or None

    try:
        configure_logging(level=log_level, fmt=log_format, log_file=log_file)
    except ValueError as e:
        parser.error(str(e))

    _logger = get_logger(__name__)
    _logger.info("ImpactGuard started with command: %s", args.command)

    if not args.command:
        parser.print_help()
        return 1

    if hasattr(args, "func"):
        result: int | list[dict[str, Any]] = args.func(args)
        return result
    else:
        parser.print_help()
        return 1


def _extract_staged_files(
    py_files: list[str],
) -> tuple[list[str], list[str], str, str] | None:
    """Extract old (HEAD) and new (staged/index) file content to temp dirs.

    Returns (old_paths, new_paths, old_base, new_base) or None on failure.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    tmpdir = tempfile.mkdtemp(prefix="impactguard_staged_")
    old_dir = Path(tmpdir) / "old"
    new_dir = Path(tmpdir) / "new"
    old_dir.mkdir()
    new_dir.mkdir()

    old_paths: list[str] = []
    new_paths: list[str] = []

    for src_file in py_files:
        old_dest = old_dir / src_file
        old_dest.parent.mkdir(parents=True, exist_ok=True)
        old_result = subprocess.run(
            ["git", "show", f"HEAD:{src_file}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if old_result.returncode == 0 and old_result.stdout:
            old_dest.write_text(old_result.stdout)
            old_paths.append(str(old_dest))

        new_dest = new_dir / src_file
        new_dest.parent.mkdir(parents=True, exist_ok=True)
        new_result = subprocess.run(
            ["git", "show", f":{src_file}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if new_result.returncode == 0 and new_result.stdout:
            new_dest.write_text(new_result.stdout)
            new_paths.append(str(new_dest))

    if not new_paths:
        return None
    return old_paths, new_paths, str(old_dir.resolve()), str(new_dir.resolve())


def _print_pipeline_summary(result: dict) -> None:
    """Print pipeline result summary to stdout."""
    comparison = result.get("comparison", {})
    print("\n=== Comparison ===")
    print(f"Breaking changes: {len(comparison.get('breaking', []))}")
    print(f"Non-breaking changes: {len(comparison.get('nonbreaking', []))}")
    _print_breaking_details(comparison)

    _print_risk_analysis(result)

    if "analysis_status" in result:
        status = result["analysis_status"]
        counters = status.get("counters", {})
        print("\n=== Analysis Status ===")
        print(f"Status: {status.get('status', 'unknown').upper()}")
        print(
            f"Counters: parse_failures={counters.get('parse_failures', 0)}, "
            f"skipped_files={counters.get('skipped_files', 0)}, "
            f"fallback_used={counters.get('fallback_used', 0)}"
        )
        runtime = status.get("runtime", {})
        if runtime:
            print(f"Runtime state: {runtime.get('state', 'unknown')}")

    if "gate" in result:
        gate = result["gate"]
        print("\n=== Gate Summary ===")
        print(f"Blocked: {str(gate.get('blocked', False)).lower()}")


def check_staged() -> int:
    """Pre-commit hook: run full pipeline on staged changes.

    Extracts full file content from git (HEAD for old, index for new)
    instead of relying on the lossy _parse_unified_diff reconstruction
    from a diff with default context length.
    """
    import os
    import subprocess

    saved = os.environ.get("SKIP_SIGNATURE_HOOK")
    if saved:
        return 0

    os.environ["SKIP_SIGNATURE_HOOK"] = "1"
    try:
        changed = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
        )
        if not changed.stdout.strip():
            return 0

        py_files = [f for f in changed.stdout.splitlines() if f.endswith(".py")]
        if not py_files:
            return 0

        extracted = _extract_staged_files(py_files)
        if extracted is None:
            return 0

        old_paths, new_paths, old_base, new_base = extracted

        from .pipeline import run_pipeline

        result = run_pipeline(
            old_files=old_paths or None,
            new_files=new_paths,
            old_base_path=old_base,
            new_base_path=new_base,
            skip_feedback_calibration=True,
        )

        _print_pipeline_summary(result)
        gate = result.get("gate", {})
        return 1 if gate.get("blocked", False) else 0
    finally:
        if saved is None:
            os.environ.pop("SKIP_SIGNATURE_HOOK", None)
        else:
            os.environ["SKIP_SIGNATURE_HOOK"] = saved


def post_commit_hook() -> int:
    """Post-commit hook: silently extract signatures from tracked .py files."""
    import os
    import subprocess
    import sys
    import tempfile

    saved = os.environ.get("SKIP_SIGNATURE_HOOK")
    if saved:
        return 0

    os.environ["SKIP_SIGNATURE_HOOK"] = "1"
    try:
        files = subprocess.run(
            ["git", "ls-files", "*.py"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError:
        return 0

    if not files:
        return 0

    try:
        result = subprocess.run(
            [sys.executable, "-m", "impactguard", "extract", *files],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            sigs_path = os.path.join(tempfile.gettempdir(), "impactguard_sigs.json")
            with open(sigs_path, "w") as f:
                f.write(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return 0
    finally:
        if saved is None:
            os.environ.pop("SKIP_SIGNATURE_HOOK", None)
        else:
            os.environ["SKIP_SIGNATURE_HOOK"] = saved
    return 0


if __name__ == "__main__":
    result = main()
    logging.shutdown()
    if isinstance(result, list):
        sys.exit(1 if any(r.get("risk") == "HIGH" for r in result) else 0)
    sys.exit(result)
