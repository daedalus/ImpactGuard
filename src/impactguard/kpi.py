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

from typing import Any


# Exposure threshold below which a HIGH item is treated as a candidate FP.
_DEFAULT_FP_THRESHOLD = 0.05


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
    total = len(report_data)

    # ── mean_severity (S dimension of S×E×C) ─────────────────────────────────
    from .risk_model import get_severity

    severities: list[float] = [
        get_severity(str(item.get("change", ""))) for item in report_data
    ]
    mean_severity = sum(severities) / total if total else 0.0

    # ── risk_distribution ────────────────────────────────────────────────────
    counts: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for item in report_data:
        level = str(item.get("risk", "UNKNOWN"))
        if level not in counts:
            level = "UNKNOWN"
        counts[level] += 1

    distribution: dict[str, dict[str, Any]] = {}
    for level, cnt in counts.items():
        distribution[level] = {
            "count": cnt,
            "rate": cnt / total if total else 0.0,
        }

    # ── mean_risk_score (exposure × confidence) ──────────────────────────────
    risk_scores: list[float] = []
    for item in report_data:
        exp = float(item.get("exposure", 0.0))
        conf = float(item.get("confidence", 0.0))
        risk_scores.append(exp * conf)
    mean_risk_score = sum(risk_scores) / total if total else 0.0

    # ── high_rate ────────────────────────────────────────────────────────────
    high_rate = counts["HIGH"] / total if total else 0.0

    # ── confidence_coverage ──────────────────────────────────────────────────
    known_count = total - counts["UNKNOWN"]
    confidence_coverage = known_count / total if total else 0.0

    # ── mean_exposure ────────────────────────────────────────────────────────
    exposures = [float(item.get("exposure", 0.0)) for item in report_data]
    mean_exposure = sum(exposures) / total if total else 0.0

    # ── mean_confidence (C dimension of S×E×C) ───────────────────────────────
    confidences: list[float] = [float(item.get("confidence", 0.0)) for item in report_data]
    mean_confidence = sum(confidences) / total if total else 0.0

    # ── transitive count/rate ─────────────────────────────────────────────────
    transitive_count = sum(1 for item in report_data if item.get("transitive"))
    transitive_rate = transitive_count / total if total else 0.0

    # ── patch_acceptance_rate ────────────────────────────────────────────────
    patch_acceptance_rate: float | None = None
    if feedback_outcomes is not None:
        n = len(feedback_outcomes)
        if n > 0:
            accepted = sum(1 for o in feedback_outcomes if o.get("accepted"))
            patch_acceptance_rate = accepted / n
        else:
            patch_acceptance_rate = 0.0

    # ── false_positive_proxy ─────────────────────────────────────────────────
    high_items = [item for item in report_data if item.get("risk") == "HIGH"]
    low_exp_high = sum(
        1 for item in high_items if float(item.get("exposure", 0.0)) < fp_threshold
    )
    false_positive_proxy = low_exp_high / len(high_items) if high_items else 0.0

    return {
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


def format_kpi_text(kpis: dict[str, Any]) -> str:
    """Format KPIs as a human-readable text dashboard.

    Args:
        kpis: Dict as returned by :func:`compute_kpis`.

    Returns:
        Multi-line string suitable for terminal output.
    """
    total = kpis.get("total", 0)
    dist = kpis.get("risk_distribution", {})
    lines: list[str] = [
        "── ImpactGuard KPI Dashboard ──────────────────────────",
        f"  Total changes analyzed : {total}",
        "",
        "  Risk distribution",
    ]

    _LEVEL_ICONS = {
        "HIGH": "🔴",
        "MEDIUM": "🟡",
        "LOW": "🟢",
        "UNKNOWN": "⚪",
    }
    for level in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        entry = dist.get(level, {"count": 0, "rate": 0.0})
        icon = _LEVEL_ICONS.get(level, "  ")
        lines.append(
            f"    {icon}  {level:<8}  {entry['count']:4d}  ({entry['rate']:.0%})"
        )

    lines.append("")

    ms = kpis.get("mean_severity", 0.0)
    lines.append(f"  Mean severity (S)      : {ms:.3f}  (avg breakage probability)")

    mean_risk = kpis.get("mean_risk_score", 0.0)
    lines.append(f"  Mean risk score (E×C)  : {mean_risk:.3f}")

    high_rate = kpis.get("high_rate", 0.0)
    lines.append(f"  HIGH rate              : {high_rate:.1%}")

    me = kpis.get("mean_exposure", 0.0)
    lines.append(f"  Mean exposure (E)      : {me:.1%}  (avg call-trace coverage)")

    mc = kpis.get("mean_confidence", 0.0)
    lines.append(f"  Mean confidence (C)    : {mc:.3f}  (avg runtime telemetry strength)")

    cc = kpis.get("confidence_coverage", 0.0)
    lines.append(f"  Confidence coverage    : {cc:.1%}  (fraction with runtime data)")

    par = kpis.get("patch_acceptance_rate")
    if par is None:
        par_str = "n/a  (no feedback data)"
    else:
        par_str = f"{par:.1%}"
    lines.append(f"  Patch acceptance rate  : {par_str}")

    fpp = kpis.get("false_positive_proxy", 0.0)
    lines.append(f"  False-positive proxy   : {fpp:.1%}  (HIGH items w/ exposure < 5%)")

    tc = kpis.get("transitive_count", 0)
    tr = kpis.get("transitive_rate", 0.0)
    lines.append(f"  Transitive items       : {tc}  ({tr:.1%} of total — indirect callers)")

    lines.append("────────────────────────────────────────────────────────")

    return "\n".join(lines)
