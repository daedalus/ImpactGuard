"""Pipeline orchestrator - connects all ImpactGuard components."""

import json
import tempfile
from pathlib import Path
from typing import Any


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
    from .extract_signatures import extract
    from .compare_signatures import compare, load
    from .analyze_module import analyze as analyze_module
    from .impact_analysis import analyze
    from .risk_gate import run as run_risk
    from .generate_report import generate_html
    from .suggest_fixes import suggest, enrich_with_fixes
    from .patch_confidence import classify_with_factors

    result: dict[str, Any] = {}

    # Use temp dir if no output_dir specified
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="impactguard_")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Step 1: Extract or load signatures
    if old_files:
        old_sigs = extract(old_files)
        old_sigs_path = str(Path(output_dir) / "old_signatures.json")
        with open(old_sigs_path, "w") as f:
            json.dump(old_sigs, f, indent=2)
    elif old_sigs_path and Path(old_sigs_path).exists():
        pass  # Use provided path
    else:
        old_sigs_path = None

    if new_files:
        new_sigs = extract(new_files)
        new_sigs_path = str(Path(output_dir) / "new_signatures.json")
        with open(new_sigs_path, "w") as f:
            json.dump(new_sigs, f, indent=2)
    elif new_sigs_path and Path(new_sigs_path).exists():
        pass  # Use provided path
    else:
        raise ValueError("Must provide new_files or new_sigs_path")

    # If no old signatures, just return new signatures
    if not old_sigs_path:
        result["signatures"] = {"new": json.load(open(new_sigs_path))}
        return result

    # Step 2: Compare signatures
    comparison = compare(old_sigs_path, new_sigs_path)
    result["comparison"] = comparison

    # Step 3: Extract call sites (if not provided)
    if not calls_path:
        calls_path = str(Path(output_dir) / "calls.json")
        all_calls: list[dict[str, Any]] = []

        # Use analyze_module for better call analysis with type information
        if new_files:
            for file_path in new_files:
                try:
                    mod_result = analyze_module(file_path)
                    if mod_result and "calls" in mod_result:
                        all_calls.extend(mod_result["calls"])
                except Exception:
                    # Fall back to basic extraction
                    from .extract_calls import extract

                    all_calls.extend(extract(Path(file_path)))

        # Also include runtime data if available
        if runtime_path and Path(runtime_path).exists():
            try:
                rt_data = json.load(open(runtime_path))
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

    # Collect Python files
    def collect_files(path: str) -> list[str]:
        p = Path(path)
        if p.is_file() and p.suffix == ".py":
            return [str(p)]
        elif p.is_dir():
            return [str(f) for f in p.rglob("*.py")]
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
    from .extract_signatures import extract

    # Get signatures
    if old_ref and new_ref:
        import subprocess
        import tempfile

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

                py_files = [f for f in result.stdout.splitlines() if f.endswith(".py") and _validate_git_path(f)]
                for py_file in py_files:
                    dest_path = dest / py_file
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        r = subprocess.run(
                            ["git", "show", f"{ref}:{py_file}"],
                            capture_output=True, text=True, timeout=30,
                        )
                    except subprocess.TimeoutExpired:
                        print(f"  Warning: Timeout extracting {py_file} from {ref}")
                        continue
                    if r.returncode == 0 and r.stdout:
                        dest_path.write_text(r.stdout)

            old_sigs = extract([str(f) for f in old_dir.rglob("*.py")])
            new_sigs = extract([str(f) for f in new_dir.rglob("*.py")])
    elif old_files and new_files:
        old_sigs = extract(old_files)
        new_sigs = extract(new_files)
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
    import re
    import subprocess
    import tempfile
    from pathlib import Path

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

    def extract_commit_files(ref: str, dest: str) -> None:
        """Extract Python files from a git commit to a directory."""
        # Validate git ref
        if not _validate_git_ref(ref):
            print(f"  Error: Invalid git reference '{ref}'", file=sys.stderr)
            return

        if files:
            # Extract only specified files
            py_files = [f for f in files if f.endswith(".py") and _validate_git_path(f)]
        else:
            # Get list of ALL Python files in the commit
            try:
                result = subprocess.run(
                    ["git", "ls-tree", "-r", "--name-only", ref],
                    capture_output=True, text=True, check=True, timeout=30
                )
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                print(f"  Error: Failed to list files from {ref}: {e}", file=sys.stderr)
                return

            py_files = [f for f in result.stdout.splitlines() if f.endswith(".py") and _validate_git_path(f)]

        if not py_files:
            print(f"  Warning: No Python files found in {ref}")
            return

        # Extract each file
        for py_file in py_files:
            # Create subdirectory structure
            dest_path = Path(dest) / py_file
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Extract file content from git with timeout
            try:
                result = subprocess.run(
                    ["git", "show", f"{ref}:{py_file}"],
                    capture_output=True, text=True, timeout=30
                )
            except subprocess.TimeoutExpired:
                print(f"  Warning: Timeout extracting {py_file} from {ref}")
                continue

            if result.returncode == 0 and result.stdout:
                dest_path.write_text(result.stdout)
            else:
                print(f"  Warning: Could not extract {py_file} from {ref}")

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
            old_files=[str(p) for p in Path(old_dir).rglob("*.py")] or None,
            new_files=[str(p) for p in Path(new_dir).rglob("*.py")] or None,
            runtime_path=runtime_path,
            output_dir=output_path or tmpdir,
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

    def check(self, path: str) -> dict[str, Any]:
        """Check a single file/directory (compare with previous version).

        Args:
            path: Path to check

        Returns:
            Analysis results
        """
        # This would need version control integration
        # For now, just extract signatures
        from .extract_signatures import extract

        files = []
        p = Path(path)
        if p.is_file():
            files = [str(p)]
        elif p.is_dir():
            files = [str(f) for f in p.rglob("*.py")]

        return {"signatures": extract(files), "status": "single_version"}
