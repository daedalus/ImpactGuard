"""Minimal KPI dashboard for ImpactGuard.

Computes a concise set of 12 key performance indicators from a risk report and
optional patch-feedback outcomes.  All values are pure Python — no external
dependencies beyond the standard library.

KPI definitions
---------------
The metrics cover all three dimensions of the S×E×C risk model plus
patch-feedback and transitive-impact quality signals.

**S (Severity)**
1. **mean_severity** — arithmetic mean of the severity score ``S`` computed
   via :func:`~impactguard.risk_model.get_severity` for each item's
   ``change`` field; reflects the inherent breakage probability of the
   changes being made.

**E (Exposure)**
2. **mean_exposure** — arithmetic mean of the ``exposure`` field across all
   items; indicates how well-exercised the changed functions are in traces.

**C (Confidence)**
3. **mean_confidence** — arithmetic mean of the ``confidence`` field across
   all items; reflects how much runtime telemetry backs each classification.
4. **confidence_coverage** — fraction of items that are *not* UNKNOWN
   (i.e., the model had enough runtime data to make a confident call).

**Composite / classification**
5. **risk_distribution** — counts and percentage rates per risk level
   (HIGH / MEDIUM / LOW / UNKNOWN).
6. **mean_risk_score** — arithmetic mean of the ``exposure × confidence``
   product across all report items (proxy for overall S×E×C without
   re-running the full model).
7. **high_rate** — fraction of report items classified HIGH risk.

**Transitive impact**
8. **transitive_count** — number of report items flagged as indirect
   (transitive) callers (``transitive=True``).
9. **transitive_rate** — fraction of items that are transitive.

**Patch quality**
10. **patch_acceptance_rate** — overall ratio of accepted patches from
    recorded feedback outcomes.  ``None`` when no feedback data is supplied.

**Noise / quality**
11. **false_positive_proxy** — fraction of HIGH-classified items whose
    ``exposure`` is below *fp_threshold* (default 0.05); items flagged HIGH
    despite very low runtime coverage are likely false positives.
"""

from datetime import UTC, datetime
from typing import Any

# Exposure threshold below which a HIGH item is treated as a candidate FP.
_DEFAULT_FP_THRESHOLD = 0.05


def _normalize_report_data(report_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop malformed report entries before KPI aggregation."""
    return [item for item in report_data if isinstance(item, dict)]


def _build_distribution(
    report_data: list[dict[str, Any]], total: int
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    """Build raw risk counts and normalized distribution data."""
    counts: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for item in report_data:
        level = str(item.get("risk", "UNKNOWN"))
        if level not in counts:
            level = "UNKNOWN"
        counts[level] += 1

    distribution = {
        level: {"count": cnt, "rate": cnt / total if total else 0.0}
        for level, cnt in counts.items()
    }
    return counts, distribution


def _mean_risk_score(report_data: list[dict[str, Any]], total: int) -> float:
    """Compute the average exposure × confidence proxy score."""
    risk_scores = [
        float(item.get("exposure", 0.0)) * float(item.get("confidence", 0.0))
        for item in report_data
    ]
    return sum(risk_scores) / total if total else 0.0


def _patch_acceptance_rate(
    feedback_outcomes: list[dict[str, Any]] | None,
) -> float | None:
    """Compute overall patch acceptance, if feedback data exists."""
    if feedback_outcomes is None:
        return None
    total = len(feedback_outcomes)
    if total == 0:
        return 0.0
    accepted = sum(1 for outcome in feedback_outcomes if outcome.get("accepted"))
    return accepted / total


def _false_positive_proxy(
    report_data: list[dict[str, Any]], fp_threshold: float
) -> float:
    """Estimate the rate of likely false-positive HIGH findings."""
    high_items = [item for item in report_data if item.get("risk") == "HIGH"]
    low_exp_high = sum(
        1 for item in high_items if float(item.get("exposure", 0.0)) < fp_threshold
    )
    return low_exp_high / len(high_items) if high_items else 0.0


def compute_kpis(
    report_data: list[dict[str, Any]],
    feedback_outcomes: list[dict[str, Any]] | None = None,
    fp_threshold: float = _DEFAULT_FP_THRESHOLD,
) -> dict[str, Any]:
    """Compute the 12-metric KPI set from a risk report.

    Covers all three S×E×C dimensions (severity, exposure, confidence) plus
    transitive-impact breakdown and patch-quality signal.

    Args:
        report_data: List of risk-report dicts as produced by
            :func:`~impactguard.risk_gate.run` or
            :func:`~impactguard.generate_report.generate_html`.
        feedback_outcomes: Optional list of patch-outcome dicts as returned
            by :func:`~impactguard.feedback.load_outcomes`.  When provided,
            ``patch_acceptance_rate`` is populated.
        fp_threshold: Exposure value below which a HIGH item is counted as a
            potential false positive (default: 0.05).

    Returns:
        Dictionary with keys:

        * ``computed_at`` — ISO-8601 UTC timestamp of when KPIs were computed
        * ``total`` — total number of report items
        * ``mean_severity`` — mean severity score S across all items
        * ``mean_exposure`` — mean exposure E across all items
        * ``mean_confidence`` — mean confidence C across all items
        * ``confidence_coverage`` — fraction of items that are not UNKNOWN
        * ``risk_distribution`` — dict with sub-keys for each level (HIGH /
          MEDIUM / LOW / UNKNOWN), each containing ``count`` and ``rate``
        * ``mean_risk_score`` — mean exposure × confidence (E×C proxy)
        * ``high_rate`` — fraction classified HIGH
        * ``transitive_count`` — count of indirect (transitive) risk items
        * ``transitive_rate`` — fraction of items that are transitive
        * ``patch_acceptance_rate`` — float in [0, 1] or None
        * ``false_positive_proxy`` — fraction of HIGH items with exposure below
          *fp_threshold*
    """
    # Filter out any non-dict entries to be robust against malformed input
    report_data = _normalize_report_data(report_data)
    total = len(report_data)

    # ── mean_severity (S dimension of S×E×C) ─────────────────────────────────
    from .risk_model import get_severity

    severities: list[float] = [
        get_severity(str(item.get("change", ""))) for item in report_data
    ]
    mean_severity = sum(severities) / total if total else 0.0

    # ── risk_distribution ────────────────────────────────────────────────────
    counts, distribution = _build_distribution(report_data, total)

    # ── mean_risk_score (exposure × confidence) ──────────────────────────────
    mean_risk_score = _mean_risk_score(report_data, total)

    # ── high_rate ────────────────────────────────────────────────────────────
    high_rate = counts["HIGH"] / total if total else 0.0

    # ── confidence_coverage ──────────────────────────────────────────────────
    known_count = total - counts["UNKNOWN"]
    confidence_coverage = known_count / total if total else 0.0

    # ── mean_exposure ────────────────────────────────────────────────────────
    exposures = [float(item.get("exposure", 0.0)) for item in report_data]
    mean_exposure = sum(exposures) / total if total else 0.0

    # ── mean_confidence (C dimension of S×E×C) ───────────────────────────────
    confidences: list[float] = [
        float(item.get("confidence", 0.0)) for item in report_data
    ]
    mean_confidence = sum(confidences) / total if total else 0.0

    # ── transitive count/rate ─────────────────────────────────────────────────
    transitive_count = sum(1 for item in report_data if item.get("transitive"))
    transitive_rate = transitive_count / total if total else 0.0

    # ── patch_acceptance_rate ────────────────────────────────────────────────
    patch_acceptance_rate = _patch_acceptance_rate(feedback_outcomes)

    # ── false_positive_proxy ─────────────────────────────────────────────────
    false_positive_proxy = _false_positive_proxy(report_data, fp_threshold)

    return {
        "computed_at": datetime.now(UTC).isoformat(),
        "total": total,
        "mean_severity": mean_severity,
        "mean_exposure": mean_exposure,
        "mean_confidence": mean_confidence,
        "confidence_coverage": confidence_coverage,
        "risk_distribution": distribution,
        "mean_risk_score": mean_risk_score,
        "high_rate": high_rate,
        "transitive_count": transitive_count,
        "transitive_rate": transitive_rate,
        "patch_acceptance_rate": patch_acceptance_rate,
        "false_positive_proxy": false_positive_proxy,
    }


def _format_metric_line(label: str, value: str, suffix: str = "") -> str:
    """Format a single KPI metric line with optional suffix."""
    if suffix:
        return f"  {label} : {value}  {suffix}"
    return f"  {label} : {value}"


def format_kpi_text(kpis: dict[str, Any]) -> str:
    """Format KPIs as a human-readable text dashboard.

    Args:
        kpis: Dict as returned by :func:`compute_kpis`.

    Returns:
        Multi-line string suitable for terminal output.
    """
    total = kpis.get("total", 0)
    dist = kpis.get("risk_distribution", {})
    computed_at = kpis.get("computed_at", "")
    lines: list[str] = [
        "── ImpactGuard KPI Dashboard ──────────────────────────",
        f"  Total changes analyzed : {total}",
    ]
    if computed_at:
        lines.append(f"  Computed at            : {computed_at}")
    lines.append("")
    lines.append("  Risk distribution")

    _level_icons = {
        "HIGH": "🔴",
        "MEDIUM": "🟡",
        "LOW": "🟢",
        "UNKNOWN": "⚪",
    }
    for level in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        entry = dist.get(level, {"count": 0, "rate": 0.0})
        icon = _level_icons.get(level, "  ")
        lines.append(
            f"    {icon}  {level:<8}  {entry['count']:4d}  ({entry['rate']:.0%})"
        )

    lines.append("")

    lines.append(_format_metric_line("Mean severity (S)", f"{kpis.get('mean_severity', 0.0):.3f}", "(avg breakage probability)"))
    lines.append(_format_metric_line("Mean risk score (E×C)", f"{kpis.get('mean_risk_score', 0.0):.3f}"))
    lines.append(_format_metric_line("HIGH rate", f"{kpis.get('high_rate', 0.0):.1%}"))
    lines.append(_format_metric_line("Mean exposure (E)", f"{kpis.get('mean_exposure', 0.0):.1%}", "(avg call-trace coverage)"))
    lines.append(_format_metric_line("Mean confidence (C)", f"{kpis.get('mean_confidence', 0.0):.3f}", "(avg runtime telemetry strength)"))
    lines.append(_format_metric_line("Confidence coverage", f"{kpis.get('confidence_coverage', 0.0):.1%}", "(fraction with runtime data)"))

    par = kpis.get("patch_acceptance_rate")
    par_str = "n/a  (no feedback data)" if par is None else f"{par:.1%}"
    lines.append(_format_metric_line("Patch acceptance rate", par_str))

    lines.append(_format_metric_line("False-positive proxy", f"{kpis.get('false_positive_proxy', 0.0):.1%}", "(HIGH items w/ exposure < 5%)"))

    tc = kpis.get("transitive_count", 0)
    tr = kpis.get("transitive_rate", 0.0)
    lines.append(_format_metric_line("Transitive items", f"{tc}  ({tr:.1%} of total — indirect callers)"))

    lines.append("────────────────────────────────────────────────────────")

    return "\n".join(lines)
