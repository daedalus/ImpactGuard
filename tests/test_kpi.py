"""Tests for the KPI dashboard module (impactguard.kpi)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from impactguard.kpi import compute_kpis, format_kpi_text

# ── fixtures / helpers ────────────────────────────────────────────────────────

_SAMPLE_REPORT: list[dict] = [
    {"function": "foo", "risk": "HIGH",    "exposure": 0.8, "confidence": 1.0},
    {"function": "bar", "risk": "MEDIUM",  "exposure": 0.4, "confidence": 0.9},
    {"function": "baz", "risk": "LOW",     "exposure": 0.1, "confidence": 0.8},
    {"function": "qux", "risk": "UNKNOWN", "exposure": 0.2, "confidence": 0.2},
    {"function": "fp",  "risk": "HIGH",    "exposure": 0.01, "confidence": 1.0},
]

_SAMPLE_FEEDBACK: list[dict] = [
    {"patch_id": "p1", "accepted": True},
    {"patch_id": "p2", "accepted": True},
    {"patch_id": "p3", "accepted": False},
    {"patch_id": "p4", "accepted": True},
]


# ── compute_kpis ──────────────────────────────────────────────────────────────


def test_total():
    kpis = compute_kpis(_SAMPLE_REPORT)
    assert kpis["total"] == 5


def test_risk_distribution_counts():
    kpis = compute_kpis(_SAMPLE_REPORT)
    dist = kpis["risk_distribution"]
    assert dist["HIGH"]["count"] == 2
    assert dist["MEDIUM"]["count"] == 1
    assert dist["LOW"]["count"] == 1
    assert dist["UNKNOWN"]["count"] == 1


def test_risk_distribution_rates_sum_to_one():
    kpis = compute_kpis(_SAMPLE_REPORT)
    dist = kpis["risk_distribution"]
    total_rate = sum(d["rate"] for d in dist.values())
    assert abs(total_rate - 1.0) < 1e-9


def test_risk_distribution_rates_match_counts():
    kpis = compute_kpis(_SAMPLE_REPORT)
    dist = kpis["risk_distribution"]
    n = kpis["total"]
    for level, entry in dist.items():
        assert abs(entry["rate"] - entry["count"] / n) < 1e-9


def test_high_rate():
    kpis = compute_kpis(_SAMPLE_REPORT)
    assert abs(kpis["high_rate"] - 2 / 5) < 1e-9


def test_confidence_coverage():
    # 4 out of 5 are not UNKNOWN
    kpis = compute_kpis(_SAMPLE_REPORT)
    assert abs(kpis["confidence_coverage"] - 4 / 5) < 1e-9


def test_mean_exposure():
    exposures = [0.8, 0.4, 0.1, 0.2, 0.01]
    expected = sum(exposures) / len(exposures)
    kpis = compute_kpis(_SAMPLE_REPORT)
    assert abs(kpis["mean_exposure"] - expected) < 1e-9


def test_mean_risk_score():
    # exposure × confidence for each item
    pairs = [(0.8, 1.0), (0.4, 0.9), (0.1, 0.8), (0.2, 0.2), (0.01, 1.0)]
    expected = sum(e * c for e, c in pairs) / len(pairs)
    kpis = compute_kpis(_SAMPLE_REPORT)
    assert abs(kpis["mean_risk_score"] - expected) < 1e-9


def test_patch_acceptance_rate_none_when_no_feedback():
    kpis = compute_kpis(_SAMPLE_REPORT)
    assert kpis["patch_acceptance_rate"] is None


def test_patch_acceptance_rate_with_feedback():
    kpis = compute_kpis(_SAMPLE_REPORT, feedback_outcomes=_SAMPLE_FEEDBACK)
    # 3 accepted out of 4
    assert abs(kpis["patch_acceptance_rate"] - 3 / 4) < 1e-9


def test_patch_acceptance_rate_empty_feedback():
    kpis = compute_kpis(_SAMPLE_REPORT, feedback_outcomes=[])
    assert kpis["patch_acceptance_rate"] == 0.0


def test_false_positive_proxy_default_threshold():
    # Only "fp" item has exposure 0.01 < 0.05 and risk HIGH
    kpis = compute_kpis(_SAMPLE_REPORT)
    # 1 out of 2 HIGH items is FP candidate
    assert abs(kpis["false_positive_proxy"] - 0.5) < 1e-9


def test_false_positive_proxy_custom_threshold():
    # With threshold 0.9, the HIGH item with exposure 0.8 is also below → both HIGH items count
    kpis = compute_kpis(_SAMPLE_REPORT, fp_threshold=0.9)
    assert kpis["false_positive_proxy"] == 1.0


def test_false_positive_proxy_no_high_items():
    report = [{"function": "a", "risk": "LOW", "exposure": 0.1, "confidence": 0.9}]
    kpis = compute_kpis(report)
    assert kpis["false_positive_proxy"] == 0.0


# ── empty report ──────────────────────────────────────────────────────────────


def test_empty_report_all_zeros():
    kpis = compute_kpis([])
    assert kpis["total"] == 0
    assert kpis["mean_risk_score"] == 0.0
    assert kpis["high_rate"] == 0.0
    assert kpis["confidence_coverage"] == 0.0
    assert kpis["mean_exposure"] == 0.0
    assert kpis["false_positive_proxy"] == 0.0
    for level in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        assert kpis["risk_distribution"][level]["count"] == 0
        assert kpis["risk_distribution"][level]["rate"] == 0.0


# ── unknown risk level defaults ───────────────────────────────────────────────


def test_missing_risk_treated_as_unknown():
    report = [{"function": "x"}]
    kpis = compute_kpis(report)
    assert kpis["risk_distribution"]["UNKNOWN"]["count"] == 1


def test_unrecognised_risk_level_treated_as_unknown():
    report = [{"function": "x", "risk": "CRITICAL"}]
    kpis = compute_kpis(report)
    assert kpis["risk_distribution"]["UNKNOWN"]["count"] == 1


# ── format_kpi_text ───────────────────────────────────────────────────────────


def test_format_kpi_text_contains_levels():
    kpis = compute_kpis(_SAMPLE_REPORT)
    text = format_kpi_text(kpis)
    for level in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        assert level in text


def test_format_kpi_text_contains_header():
    kpis = compute_kpis([])
    text = format_kpi_text(kpis)
    assert "KPI" in text


def test_format_kpi_text_no_feedback_shows_na():
    kpis = compute_kpis(_SAMPLE_REPORT)
    text = format_kpi_text(kpis)
    assert "n/a" in text


def test_format_kpi_text_with_feedback_shows_percentage():
    kpis = compute_kpis(_SAMPLE_REPORT, feedback_outcomes=_SAMPLE_FEEDBACK)
    text = format_kpi_text(kpis)
    # 75% acceptance rate — formatted as "75.0%"
    assert "75.0%" in text


def test_format_kpi_text_returns_string():
    kpis = compute_kpis(_SAMPLE_REPORT)
    assert isinstance(format_kpi_text(kpis), str)


# ── CLI integration ───────────────────────────────────────────────────────────


def test_cli_kpi_prints_dashboard(tmp_path):
    """CLI `kpi` subcommand prints the text dashboard to stdout."""
    import subprocess

    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(_SAMPLE_REPORT))

    result = subprocess.run(
        [sys.executable, "-m", "impactguard", "kpi", str(report_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "KPI" in result.stdout
    assert "HIGH" in result.stdout


def test_cli_kpi_json_output(tmp_path):
    """CLI `kpi --output` writes a parseable JSON file."""
    import subprocess

    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(_SAMPLE_REPORT))
    out_file = tmp_path / "kpis.json"

    result = subprocess.run(
        [
            sys.executable, "-m", "impactguard", "kpi",
            str(report_file), "-o", str(out_file),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(out_file.read_text())
    assert "total" in data
    assert "risk_distribution" in data


def test_cli_kpi_missing_report(tmp_path):
    """CLI `kpi` exits with code 1 for a missing report file."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "impactguard", "kpi", str(tmp_path / "nope.json")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_cli_kpi_with_feedback(tmp_path):
    """CLI `kpi --feedback-path` includes acceptance rate."""
    import subprocess

    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(_SAMPLE_REPORT))
    fb_file = tmp_path / "feedback.json"
    fb_file.write_text(json.dumps(_SAMPLE_FEEDBACK))

    result = subprocess.run(
        [
            sys.executable, "-m", "impactguard", "kpi",
            str(report_file), "--feedback-path", str(fb_file),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "75.0%" in result.stdout
