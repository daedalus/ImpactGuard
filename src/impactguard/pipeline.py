"""Pipeline orchestrator - connects all ImpactGuard components."""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _validate_git_ref(ref: str) -> bool:
    """Validate git ref format to prevent command injection.

    Allows: alphanumeric, dots, hyphens, slashes, underscores, ~, ^, @, {, }
    Disallows: shell metacharacters, path traversal
    """
    if not ref or len(ref) > 255:
        return False
    # Disallow shell metacharacters
    if any(c in ref for c in ['|', ';', '&', '$', '`', '!', '(', ')', '<', '>']):
        return False
    # Disallow path traversal
    if '..' in ref or ref.startswith('/'):
        return False
    # Allow safe git ref characters
    if not re.match(r'^[a-zA-Z0-9._\-/~^@{}]+$', ref):
        return False
    return True


def _validate_git_path(path: str) -> bool:
    """Validate file path from git to prevent path traversal."""
    if not path or len(path) > 255:
        return False
    # Disallow path traversal
    if '..' in path or path.startswith('/') or path.startswith('\\'):
        return False
    # Must be a relative path
    if Path(path).is_absolute():
        return False
    return True


def _extract_by_language(
    files: list[str],
    base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract signatures from *files* using the registry extractor for each file.

    Files whose extension has no registered extractor are silently skipped.

    Args:
        files: Source file paths (any mix of languages).
        base_path: Optional base path passed through to each extractor.

    Returns:
        Combined list of signature dicts from all supported files.
    """
    from .languages.registry import get_extractor as _get_extractor

    groups: dict[str, tuple[Any, list[str]]] = {}
    for f in files:
        extractor = _get_extractor(f)
        if extractor is None:
            continue
        lang = extractor.language
        if lang not in groups:
            groups[lang] = (extractor, [])
        groups[lang][1].append(f)

    all_sigs: list[dict[str, Any]] = []
    for extractor, lang_files in groups.values():
        all_sigs.extend(extractor.extract_signatures(lang_files, base_path=base_path))
    return all_sigs


def run_pipeline(
    old_files: list[str] | None = None,
    new_files: list[str] | None = None,
    old_sigs_path: str | None = None,
    new_sigs_path: str | None = None,
    calls_path: str | None = None,
    runtime_path: str | None = None,
    output_dir: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full ImpactGuard pipeline.

    This orchestrates:
    1. Extract signatures from old and new code
    2. Compare signatures to detect breaking changes
    3. Extract call sites
    4. Analyze impact on call sites
    5. Assess risk with runtime data
    6. Generate HTML report
    7. Suggest fixes with confidence scoring

    Args:
        old_files: List of old Python files (for extraction)
        new_files: List of new Python files (for extraction)
        old_sigs_path: Path to old signatures JSON (alternative to old_files)
        new_sigs_path: Path to new signatures JSON (alternative to new_files)
        calls_path: Path to call sites JSON
        runtime_path: Path to runtime data JSON
        output_dir: Directory for output files (default: temp dir)
        config: Optional configuration dictionary

    Returns:
        Dictionary with keys:
        - signatures: {"old": [...], "new": [...]}
        - comparison: {"breaking": [...], "nonbreaking": [...]}
        - impact: [...]  # impact analysis results
        - risk: [...]  # risk assessment results
        - report_html: str  # HTML report content
        - fixes: [...]  # suggested fixes
    """
    from .compare_signatures import compare, load
    from .analyze_module import analyze as analyze_module
    from .impact_analysis import analyze
    from .risk_gate import run as run_risk
    from .generate_report import generate_html
    from .suggest_fixes import suggest, enrich_with_fixes
    from .patch_confidence import classify_with_factors
    from .languages.registry import get_extractor as _get_extractor

    result: dict[str, Any] = {}

    # Use temp dir if no output_dir specified
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="impactguard_")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Step 1: Extract or load signatures
    if old_files:
        old_sigs = _extract_by_language(old_files)
        old_sigs_path = str(Path(output_dir) / "old_signatures.json")
        with open(old_sigs_path, "w") as f:
            json.dump(old_sigs, f, indent=2)
    elif old_sigs_path and Path(old_sigs_path).exists():
        pass  # Use provided path
    else:
        old_sigs_path = None

    if new_files:
        new_sigs = _extract_by_language(new_files)
        new_sigs_path = str(Path(output_dir) / "new_signatures.json")
        with open(new_sigs_path, "w") as f:
            json.dump(new_sigs, f, indent=2)
    elif new_sigs_path and Path(new_sigs_path).exists():
        pass  # Use provided path
    else:
        raise ValueError("Must provide new_files or new_sigs_path")

    # If no old signatures, just return new signatures
    if not old_sigs_path:
        with open(new_sigs_path) as f:
            result["signatures"] = {"new": json.load(f)}
        return result

    # Step 2: Compare signatures
    comparison = compare(old_sigs_path, new_sigs_path)
    result["comparison"] = comparison

    # Step 3: Extract call sites (if not provided)
    if not calls_path:
        calls_path = str(Path(output_dir) / "calls.json")
        all_calls: list[dict[str, Any]] = []

        # Use analyze_module for Python files; language extractor for others
        if new_files:
            for file_path in new_files:
                extractor = _get_extractor(file_path)
                if extractor is None:
                    continue
                if extractor.language == "python":
                    try:
                        mod_result = analyze_module(file_path)
                        if mod_result and "calls" in mod_result:
                            all_calls.extend(mod_result["calls"])
                    except Exception:
                        # Fall back to basic extraction
                        from .extract_calls import extract as _extract_calls

                        all_calls.extend(_extract_calls(Path(file_path)))
                else:
                    try:
                        all_calls.extend(extractor.extract_calls(Path(file_path)))
                    except Exception:
                        pass

        # Also include runtime data if available
        if runtime_path and Path(runtime_path).exists():
            try:
                with open(runtime_path) as f:
                    rt_data = json.load(f)
                for item in rt_data:
                    all_calls.append(
                        {
                            "fqname": item.get("function", ""),
                            "file": "runtime",
                            "lineno": 0,
                            "args": item.get("args_count", 0),
                            "kwargs": item.get("kwargs", []),
                            "has_starargs": False,
                            "has_kwargs": False,
                        }
                    )
            except (json.JSONDecodeError, OSError) as e:
                print(f"Warning: Failed to process runtime data: {e}", file=sys.stderr)

        with open(calls_path, "w") as f:
            json.dump(all_calls, f, indent=2)

    # Step 4: Analyze impact
    impact = analyze(new_sigs_path, calls_path, runtime_path)
    result["impact"] = impact

    # Step 5: Assess risk
    diff_path = str(Path(output_dir) / "diff.txt")
    with open(diff_path, "w") as f:
        for change in comparison["breaking"]:
            f.write(f"{change}\n")

    risk_report_path = str(Path(output_dir) / "risk_report.json")
    risk = run_risk(diff_path, runtime_path or "", risk_report_path)
    result["risk"] = risk

    # Step 6: Generate HTML report
    html = generate_html(risk)
    result["report_html"] = html

    # Step 7: Suggest fixes with confidence
    fixes = []
    for item in risk:
        if "patches" in item or "callsite_patches" in item:
            fix_suggestions = suggest(item, [item])
            enriched = enrich_with_fixes(item, [item])
            fixes.extend(enriched)
    result["fixes"] = fixes

    # Step 8: Semver recommendation
    from .semver import format_semver_recommendation
    result["semver"] = format_semver_recommendation(comparison)

    # Add signatures to result
    with open(old_sigs_path) as f:
        result["signatures"] = {"old": json.load(f), "new": []}
    with open(new_sigs_path) as f:
        result["signatures"]["new"] = json.load(f)

    return result


def quick_check(
    old_path: str,
    new_path: str,
    runtime_path: str | None = None,
) -> dict[str, Any]:
    """Quick check between two Python files or directories.

    Args:
        old_path: Path to old Python file/directory
        new_path: Path to new Python file/directory
        runtime_path: Optional path to runtime data

    Returns:
        Pipeline result dictionary
    """
    from .extract_signatures import extract

    # Collect files with a registered language extractor
    def collect_files(path: str) -> list[str]:
        from .languages.registry import get_extractor as _get_extractor

        p = Path(path)
        if p.is_file():
            return [str(p)] if _get_extractor(str(p)) is not None else []
        elif p.is_dir():
            return [
                str(f)
                for f in p.rglob("*")
                if f.is_file() and _get_extractor(str(f)) is not None
            ]
        return []

    old_files = collect_files(old_path)
    new_files = collect_files(new_path)

    return run_pipeline(
        old_files=old_files,
        new_files=new_files,
        runtime_path=runtime_path,
    )


def generate_changelog(
    old_ref: str | None = None,
    new_ref: str | None = None,
    old_files: list[str] | None = None,
    new_files: list[str] | None = None,
    output_path: str | None = None,
) -> str:
    """Generate a changelog from signature diffs.

    Args:
        old_ref: Git reference for old version (optional).
        new_ref: Git reference for new version (optional).
        old_files: List of old Python files (alternative to old_ref).
        new_files: List of new Python files (alternative to new_ref).
        output_path: Path to write changelog (optional).

    Returns:
        Changelog markdown string.
    """
    from .compare_signatures import compare

    # Get signatures
    if old_ref and new_ref:
        import subprocess
        import tempfile
        from .languages.registry import get_extractor as _get_extractor

        # Validate git refs
        for ref in [old_ref, new_ref]:
            if not _validate_git_ref(ref):
                raise ValueError(f"Invalid git reference: '{ref}'")

        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = Path(tmpdir) / "old"
            new_dir = Path(tmpdir) / "new"
            old_dir.mkdir()
            new_dir.mkdir()

            # Extract files from git
            for ref, dest in [(old_ref, old_dir), (new_ref, new_dir)]:
                try:
                    result = subprocess.run(
                        ["git", "ls-tree", "-r", "--name-only", ref],
                        capture_output=True, text=True, timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    raise RuntimeError(f"Timeout listing files from {ref}")

                src_files = [
                    f for f in result.stdout.splitlines()
                    if _get_extractor(f) is not None and _validate_git_path(f)
                ]
                for src_file in src_files:
                    dest_path = dest / src_file
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        r = subprocess.run(
                            ["git", "show", f"{ref}:{src_file}"],
                            capture_output=True, text=True, timeout=30,
                        )
                    except subprocess.TimeoutExpired:
                        print(f"  Warning: Timeout extracting {src_file} from {ref}")
                        continue
                    if r.returncode == 0 and r.stdout:
                        dest_path.write_text(r.stdout)

            old_sigs = _extract_by_language([str(f) for f in old_dir.rglob("*") if f.is_file()])
            new_sigs = _extract_by_language([str(f) for f in new_dir.rglob("*") if f.is_file()])
    elif old_files and new_files:
        old_sigs = _extract_by_language(old_files)
        new_sigs = _extract_by_language(new_files)
    else:
        raise ValueError("Must provide either git refs or file lists")

    # Save to temp files and compare
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        old_path = Path(tmpdir) / "old.json"
        new_path = Path(tmpdir) / "new.json"
        old_path.write_text(json.dumps(old_sigs))
        new_path.write_text(json.dumps(new_sigs))

        comparison = compare(str(old_path), str(new_path))

    # Generate changelog
    lines = ["## [Unreleased]\n"]

    # Group changes by type
    added = []
    removed = []
    changed_breaking = []
    changed_nonbreaking = []

    for item in comparison.get("nonbreaking", []):
        if item.startswith("ADDED: "):
            added.append(item.replace("ADDED: ", ""))
        elif item.startswith("OPTIONAL POSITIONAL ADDED: "):
            changed_nonbreaking.append(item.replace("OPTIONAL POSITIONAL ADDED: ", ""))
        elif item.startswith("OPTIONAL KWONLY ADDED: "):
            changed_nonbreaking.append(item.replace("OPTIONAL KWONLY ADDED: ", ""))

    for item in comparison.get("breaking", []):
        if item.startswith("REMOVED: "):
            removed.append(item.replace("REMOVED: ", ""))
        elif "POSITIONAL" in item or "KWONLY" in item or "REQUIRED" in item:
            changed_breaking.append(item)

    if added:
        lines.append("### Added")
        for item in added:
            # Extract function name from fqname
            func_name = item.split(":")[-1] if ":" in item else item
            lines.append(f"- `{func_name}` - New function/method added")
        lines.append("")

    if changed_nonbreaking:
        lines.append("### Changed")
        for item in changed_nonbreaking:
            func_name = item.split(":")[-1] if ":" in item else item
            lines.append(f"- `{func_name}` - Signature modified (non-breaking)")
        lines.append("")

    if removed:
        lines.append("### Removed")
        for item in removed:
            func_name = item.split(":")[-1] if ":" in item else item
            lines.append(f"- `{func_name}` - Function/method removed")
        lines.append("")

    if changed_breaking:
        lines.append("### Breaking Changes")
        for item in changed_breaking:
            lines.append(f"- {item}")
        lines.append("")

    changelog = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(changelog)

    return changelog


def run_pipeline_git(
    old_ref: str,
    new_ref: str,
    files: list[str] | None = None,
    runtime_path: str | None = None,
    output_path: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run pipeline comparing two git commits.

    Args:
        old_ref: Git reference (commit, branch, tag) for old version
        new_ref: Git reference for new version
        files: Optional list of specific files to compare (relative to repo root)
        runtime_path: Path to runtime data JSON
        output_path: Path for HTML report output
        config: Optional configuration dictionary

    Returns:
        Same as run_pipeline()
    """
    import subprocess
    from .languages.registry import get_extractor as _get_extractor

    def extract_commit_files(ref: str, dest: str) -> None:
        """Extract supported source files from a git commit to a directory."""
        # Validate git ref
        if not _validate_git_ref(ref):
            print(f"  Error: Invalid git reference '{ref}'", file=sys.stderr)
            return

        if files:
            # Extract only specified files that have a known extractor
            src_files = [f for f in files if _get_extractor(f) is not None and _validate_git_path(f)]
        else:
            # Get list of ALL supported source files in the commit
            try:
                result = subprocess.run(
                    ["git", "ls-tree", "-r", "--name-only", ref],
                    capture_output=True, text=True, check=True, timeout=30
                )
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                print(f"  Error: Failed to list files from {ref}: {e}", file=sys.stderr)
                return

            src_files = [
                f for f in result.stdout.splitlines()
                if _get_extractor(f) is not None and _validate_git_path(f)
            ]

        if not src_files:
            print(f"  Warning: No supported source files found in {ref}")
            return

        # Extract each file
        for src_file in src_files:
            # Create subdirectory structure
            dest_path = Path(dest) / src_file
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Extract file content from git with timeout
            try:
                result = subprocess.run(
                    ["git", "show", f"{ref}:{src_file}"],
                    capture_output=True, text=True, timeout=30
                )
            except subprocess.TimeoutExpired:
                print(f"  Warning: Timeout extracting {src_file} from {ref}")
                continue

            if result.returncode == 0 and result.stdout:
                dest_path.write_text(result.stdout)
            else:
                print(f"  Warning: Could not extract {src_file} from {ref}")

    with tempfile.TemporaryDirectory() as tmpdir:
        old_dir = f"{tmpdir}/old"
        new_dir = f"{tmpdir}/new"
        Path(old_dir).mkdir(parents=True, exist_ok=True)
        Path(new_dir).mkdir(parents=True, exist_ok=True)

        print(f"Extracting files from {old_ref}...")
        extract_commit_files(old_ref, old_dir)
        print(f"Extracting files from {new_ref}...")
        extract_commit_files(new_ref, new_dir)

        return run_pipeline(
            old_files=[str(p) for p in Path(old_dir).rglob("*") if p.is_file()] or None,
            new_files=[str(p) for p in Path(new_dir).rglob("*") if p.is_file()] or None,
            runtime_path=runtime_path,
            output_dir=output_path or tmpdir,
            config=config,
        )


def _parse_unified_diff(diff_text: str) -> dict[str, tuple[str, str]]:
    """Parse a unified diff and return old/new content per supported source file.

    For each changed file the returned tuple contains:
      - old_content: context lines + removed lines (as they appeared before)
      - new_content: context lines + added lines (as they appear after)

    Only files whose extension is registered in the language registry are
    included in the result.  Unsupported files (Makefile, HTML, etc.) are
    silently skipped.
    """
    from .languages.registry import get_extractor as _get_extractor

    files: dict[str, tuple[str, str]] = {}
    old_lines: list[str] = []
    new_lines: list[str] = []
    old_name: str | None = None
    new_name: str | None = None

    def _save_current() -> None:
        # For renamed files, prefer new_name as the canonical key.
        name = new_name if new_name is not None else old_name
        if name and _get_extractor(name) is not None:
            files[name] = ("\n".join(old_lines), "\n".join(new_lines))

    for line in diff_text.splitlines():
        if line.startswith("--- "):
            _save_current()
            old_name = line[4:].split("\t")[0].strip()
            if old_name.startswith("a/"):
                old_name = old_name[2:]
            if old_name == "/dev/null":
                old_name = None
            new_name = None
            old_lines = []
            new_lines = []
        elif line.startswith("+++ "):
            new_name = line[4:].split("\t")[0].strip()
            if new_name.startswith("b/"):
                new_name = new_name[2:]
            if new_name == "/dev/null":
                new_name = None
        elif line.startswith("@@"):
            pass  # hunk header – no content to collect
        elif line.startswith("-") and not line.startswith("---"):
            old_lines.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            new_lines.append(line[1:])
        elif line.startswith(" "):
            # context line – present in both versions
            old_lines.append(line[1:])
            new_lines.append(line[1:])

    _save_current()
    return files


def run_pipeline_diff_content(
    diff_text: str,
    runtime_path: str | None = None,
    output_dir: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full ImpactGuard pipeline on unified diff content (as a string).

    Equivalent to :func:`run_pipeline_diff` but accepts the diff text directly
    instead of a file path.  Useful when the diff is read from stdin or
    produced in-memory (e.g. ``diff A B | impactguard check-diff --pipe``).

    Files in the diff whose extension has no registered language extractor
    (Makefile, HTML, README, etc.) are silently skipped.

    Args:
        diff_text: Unified diff / patch content as a string.
        runtime_path: Optional path to runtime data JSON.
        output_dir: Directory for output files (default: temp dir).
        config: Optional configuration dictionary.

    Returns:
        Same dictionary as :func:`run_pipeline`.

    Raises:
        ValueError: If the diff contains no files with a supported language.
    """
    file_contents = _parse_unified_diff(diff_text)

    if not file_contents:
        raise ValueError("No supported file changes found in diff")

    with tempfile.TemporaryDirectory() as tmpdir:
        old_dir = Path(tmpdir) / "old"
        new_dir = Path(tmpdir) / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        old_files: list[str] = []
        new_files: list[str] = []

        for rel_path, (old_src, new_src) in file_contents.items():
            if old_src.strip():
                dest = old_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(old_src)
                old_files.append(str(dest))
            if new_src.strip():
                dest = new_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(new_src)
                new_files.append(str(dest))

        if not new_files:
            raise ValueError("Diff contains only deletions – nothing to analyze")

        effective_output = output_dir or tempfile.mkdtemp(prefix="impactguard_diff_")

        return run_pipeline(
            old_files=old_files or None,
            new_files=new_files,
            runtime_path=runtime_path,
            output_dir=effective_output,
            config=config,
        )


def run_pipeline_diff(
    diff_path: str,
    runtime_path: str | None = None,
    output_dir: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full ImpactGuard pipeline on a unified diff / patch file.

    The diff is parsed to reconstruct the old and new source content for every
    changed file in a supported language, and then the standard pipeline is
    executed on those reconstructed versions.  Files in the diff with
    unsupported extensions (Makefile, HTML, README, etc.) are silently skipped.

    Args:
        diff_path: Path to a unified diff / patch file.
        runtime_path: Optional path to runtime data JSON.
        output_dir: Directory for output files (default: temp dir).
        config: Optional configuration dictionary.

    Returns:
        Same dictionary as :func:`run_pipeline`.

    Raises:
        FileNotFoundError: If *diff_path* does not exist.
        ValueError: If the diff contains no files with a supported language.
    """
    diff_text = Path(diff_path).read_text()
    try:
        return run_pipeline_diff_content(
            diff_text,
            runtime_path=runtime_path,
            output_dir=output_dir,
            config=config,
        )
    except ValueError as exc:
        # Re-raise with the file path included in the error message.
        raise ValueError(f"{exc} (diff file: {diff_path})") from exc


def run_pipeline_commit(
    commit_ref: str,
    files: list[str] | None = None,
    runtime_path: str | None = None,
    output_path: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full ImpactGuard pipeline on a single git commit.

    This automatically derives the parent commit so you do not need to
    supply two refs manually.  Equivalent to::

        run_pipeline_git(parent_of(commit_ref), commit_ref, ...)

    Args:
        commit_ref: Git reference (commit SHA, branch, or tag) to analyze.
        files: Optional list of specific files to compare (relative to repo root).
        runtime_path: Path to runtime data JSON.
        output_path: Path for output files / HTML report.
        config: Optional configuration dictionary.

    Returns:
        Same dictionary as :func:`run_pipeline`.

    Raises:
        ValueError: If *commit_ref* is not a valid git reference or has no parent.
    """
    if not _validate_git_ref(commit_ref):
        raise ValueError(f"Invalid git reference: '{commit_ref}'")

    try:
        result = subprocess.run(
            ["git", "rev-parse", f"{commit_ref}^"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        parent_ref = result.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Timeout resolving parent of '{commit_ref}'") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"Cannot find parent commit for '{commit_ref}'. "
            "Initial commits have no parent."
        ) from exc

    return run_pipeline_git(
        old_ref=parent_ref,
        new_ref=commit_ref,
        files=files,
        runtime_path=runtime_path,
        output_path=output_path,
        config=config,
    )


class ImpactGuard:
    """Unified API class for ImpactGuard."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize ImpactGuard with optional config.

        Args:
            config: Configuration dictionary
        """
        self.config = config or {}

    def analyze(
        self,
        old_path: str,
        new_path: str,
        runtime_path: str | None = None,
    ) -> dict[str, Any]:
        """Analyze impact between two versions.

        Args:
            old_path: Path to old code (file or directory)
            new_path: Path to new code (file or directory)
            runtime_path: Optional path to runtime data

        Returns:
            Analysis results dictionary
        """
        return quick_check(old_path, new_path, runtime_path)

    def extract(self, files: list[str]) -> list[dict[str, Any]]:
        """Extract signatures from files.

        Args:
            files: List of Python file paths

        Returns:
            List of signature dictionaries
        """
        from .extract_signatures import extract

        return extract(files)

    def compare(
        self, old_sigs: str, new_sigs: str
    ) -> dict[str, list[str]]:
        """Compare two signature snapshots.

        Args:
            old_sigs: Path to old signatures JSON
            new_sigs: Path to new signatures JSON

        Returns:
            Dictionary with 'breaking' and 'nonbreaking' lists
        """
        from .compare_signatures import compare

        return compare(old_sigs, new_sigs)

    def check(self, path: str, baseline_path: str | None = None) -> dict[str, Any]:
        """Check a single file/directory against a stored baseline.

        When a baseline exists at *baseline_path* (or the default path), this
        performs a full comparison and risk analysis against it.  Otherwise it
        just extracts and returns the current signatures.

        Args:
            path: Path to file or directory to check.
            baseline_path: Optional explicit path to a baseline JSON file.

        Returns:
            Full pipeline result dict when a baseline is available, or
            ``{"signatures": [...], "status": "no_baseline"}`` when no
            baseline has been saved yet.
        """
        from .baseline import compare_with_baseline, baseline_exists, DEFAULT_BASELINE_PATH
        from .extract_signatures import extract

        files: list[str] = []
        p = Path(path)
        if p.is_file():
            files = [str(p)]
        elif p.is_dir():
            files = [str(f) for f in p.rglob("*.py")]

        effective_baseline = baseline_path or DEFAULT_BASELINE_PATH
        if baseline_exists(effective_baseline):
            return compare_with_baseline(files, effective_baseline)

        # No baseline yet — just return current signatures
        return {"signatures": extract(files), "status": "no_baseline"}
