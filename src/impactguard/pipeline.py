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
    from .extract_calls import extract as extract_calls
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
        # In real usage, calls would come from runtime or static analysis
        with open(calls_path, "w") as f:
            json.dump([], f)

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
