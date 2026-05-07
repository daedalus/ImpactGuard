"""Robustness Evaluator — composite robustness scoring for ImpactGuard test suites.

This module computes a Robustness Score (R) that weights adversarial test
performance more heavily than normal tests, penalizes low coverage, and
reflects actual pass rates.  It also exposes an Adversarial Fragility Index
(F) that isolates exactly how much adversarial conditions degrade performance.

Composite Robustness Score
--------------------------
R = C × (α × P_a + (1 − α) × P_n)

Where:
  C   = coverage ratio  (0 – 1)
  α   = adversarial weight (recommended: 0.5 general, 0.65 security, 0.75 red-team)
  P_a = adversarial pass rate  (passing_adv / n_adversarial)
  P_n = normal      pass rate  (passing_norm / n_normal)

With category diversity penalty (optional):
  D   = categories with ≥ 1 pass / total categories
  R_d = C × D × (α × P_a + (1 − α) × P_n)

Adversarial Fragility Index
---------------------------
F = 1 − (P_a / P_n)
  F ≈ 0  →  robust  (adversarial ≈ normal performance)
  F ≈ 1  →  brittle (adversarial performance collapses)

Adversarial Budget Allocation (default target)
----------------------------------------------
Category              | Target % of adversarial budget
Boundary/edge cases   | 30%
Semantic perturbation | 25%
Evasion/obfuscation   | 25%
Compositional attacks | 20%
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

# Minimum required adversarial coverage fraction (25 %).
ADVERSARIAL_COVERAGE_MIN: float = 0.25

# Default adversarial weight for a security-sensitive context.
DEFAULT_ALPHA: float = 0.65

# Canonical adversarial budget per category (must sum to 1.0).
ADVERSARIAL_BUDGET: dict[str, float] = {
    "boundary": 0.30,
    "semantic": 0.25,
    "evasion": 0.25,
    "compositional": 0.20,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CategoryStats:
    """Pass/fail counts for a single adversarial category."""

    name: str
    total: int
    passing: int

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passing / self.total


@dataclass
class RobustnessResult:
    """Full robustness evaluation result."""

    # --- inputs (normalised) ------------------------------------------------
    n_total: int
    n_adversarial: int
    n_normal: int
    passing_adv: int
    passing_norm: int
    coverage: float
    alpha: float

    # --- primary metrics ----------------------------------------------------
    p_adversarial: float  # adversarial pass rate
    p_normal: float  # normal pass rate
    robustness_score: float  # R  (no diversity penalty)
    robustness_score_with_diversity: float | None  # R_d (with diversity)
    fragility_index: float | None  # F  (None when P_n == 0)

    # --- secondary metrics --------------------------------------------------
    adversarial_ratio: float  # N_a / N_total
    meets_adversarial_minimum: bool  # adversarial_ratio >= 25 %
    diversity_score: float | None  # D (None when no category data)
    categories: list[CategoryStats] = field(default_factory=list)

    # --- interpretation helpers ---------------------------------------------
    @property
    def robustness_label(self) -> str:
        r = self.robustness_score
        if r >= 0.80:
            return "EXCELLENT"
        if r >= 0.65:
            return "GOOD"
        if r >= 0.45:
            return "FAIR"
        return "POOR"

    @property
    def fragility_label(self) -> str | None:
        if self.fragility_index is None:
            return None
        f = self.fragility_index
        if f <= 0.10:
            return "ROBUST"
        if f <= 0.25:
            return "MODERATE"
        if f <= 0.50:
            return "BRITTLE"
        return "VERY_BRITTLE"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["robustness_label"] = self.robustness_label
        d["fragility_label"] = self.fragility_label
        return d


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


def evaluate_robustness(
    n_total: int,
    n_adversarial: int,
    passing_adv: int,
    passing_norm: int,
    coverage: float,
    alpha: float = DEFAULT_ALPHA,
    categories: list[CategoryStats] | None = None,
) -> RobustnessResult:
    """Compute the composite Robustness Score and related metrics.

    Parameters
    ----------
    n_total:
        Total number of tests executed (adversarial + normal).
    n_adversarial:
        Number of tests classified as adversarial.
    passing_adv:
        Number of adversarial tests that passed.
    passing_norm:
        Number of normal tests that passed.
    coverage:
        Code coverage ratio in [0.0, 1.0].
    alpha:
        Adversarial weight ∈ (0, 1).  Higher values penalise poor adversarial
        performance more strongly.  Defaults to 0.65 (security context).
    categories:
        Optional per-category pass/fail breakdown.  When supplied, a diversity
        score D and a diversity-penalised score R_d are computed.

    Returns
    -------
    RobustnessResult
        Fully populated result object.

    Raises
    ------
    ValueError
        If any input is out of its valid range.
    """
    # --- validation ---------------------------------------------------------
    if n_total < 0:
        raise ValueError(f"n_total must be >= 0, got {n_total}")
    if not (0 <= n_adversarial <= n_total):
        raise ValueError(f"n_adversarial must be in [0, n_total], got {n_adversarial}")
    if not (0.0 <= coverage <= 1.0):
        raise ValueError(f"coverage must be in [0.0, 1.0], got {coverage}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0.0, 1.0), got {alpha}")

    n_normal = n_total - n_adversarial

    if n_adversarial > 0 and not (0 <= passing_adv <= n_adversarial):
        raise ValueError(
            f"passing_adv must be in [0, n_adversarial], got {passing_adv}"
        )
    if n_normal > 0 and not (0 <= passing_norm <= n_normal):
        raise ValueError(f"passing_norm must be in [0, n_normal], got {passing_norm}")

    # --- pass rates ---------------------------------------------------------
    p_adv = passing_adv / n_adversarial if n_adversarial > 0 else 0.0
    p_norm = passing_norm / n_normal if n_normal > 0 else 0.0

    # --- composite robustness score (no diversity) --------------------------
    weighted = alpha * p_adv + (1.0 - alpha) * p_norm
    r = coverage * weighted

    # --- adversarial fragility index ----------------------------------------
    fragility: float | None = None
    # Only compute fragility when p_norm is meaningful (≥ 5% pass rate)
    if p_norm >= 0.05:
        fragility = 1.0 - (p_adv / p_norm)

    # --- diversity metrics --------------------------------------------------
    diversity_score: float | None = None
    r_diversity: float | None = None

    if categories:
        total_cats = len(categories)
        cats_with_pass = sum(1 for c in categories if c.passing > 0)
        diversity_score = cats_with_pass / total_cats if total_cats > 0 else 0.0
        r_diversity = coverage * diversity_score * weighted

    # --- adversarial ratio / minimum check ----------------------------------
    adv_ratio = n_adversarial / n_total if n_total > 0 else 0.0
    meets_min = adv_ratio >= ADVERSARIAL_COVERAGE_MIN

    return RobustnessResult(
        n_total=n_total,
        n_adversarial=n_adversarial,
        n_normal=n_normal,
        passing_adv=passing_adv,
        passing_norm=passing_norm,
        coverage=coverage,
        alpha=alpha,
        p_adversarial=p_adv,
        p_normal=p_norm,
        robustness_score=r,
        robustness_score_with_diversity=r_diversity,
        fragility_index=fragility,
        adversarial_ratio=adv_ratio,
        meets_adversarial_minimum=meets_min,
        diversity_score=diversity_score,
        categories=categories or [],
    )


# ---------------------------------------------------------------------------
# Pretty-print helper
# ---------------------------------------------------------------------------


def _format_report(result: RobustnessResult) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  ImpactGuard — Robustness Evaluation Report")
    lines.append("=" * 60)

    lines.append("\n── Test Composition ──────────────────────────────────────")
    lines.append(f"  Total tests        : {result.n_total}")
    lines.append(f"  Adversarial tests  : {result.n_adversarial}")
    lines.append(f"  Normal tests       : {result.n_normal}")
    adv_pct = result.adversarial_ratio * 100
    min_flag = "✓" if result.meets_adversarial_minimum else "✗ (< 25% minimum)"
    lines.append(f"  Adversarial ratio  : {adv_pct:.1f}%  {min_flag}")

    lines.append("\n── Pass Rates ────────────────────────────────────────────")
    lines.append(f"  P_adversarial (P_a): {result.p_adversarial:.3f}")
    lines.append(f"  P_normal      (P_n): {result.p_normal:.3f}")
    lines.append(f"  Coverage      (C)  : {result.coverage:.3f}")
    lines.append(f"  Alpha         (α)  : {result.alpha:.2f}")

    if result.diversity_score is not None:
        lines.append(f"  Diversity     (D)  : {result.diversity_score:.3f}")

    lines.append("\n── Primary Metrics ───────────────────────────────────────")
    lines.append(
        f"  Robustness Score (R)          : {result.robustness_score:.4f}"
        f"  [{result.robustness_label}]"
    )
    if result.robustness_score_with_diversity is not None:
        lines.append(
            f"  Robustness + Diversity (R_d)  : "
            f"{result.robustness_score_with_diversity:.4f}"
        )
    if result.fragility_index is not None:
        lines.append(
            f"  Fragility Index (F)           : {result.fragility_index:.4f}"
            f"  [{result.fragility_label}]"
        )
    else:
        lines.append("  Fragility Index (F)           : N/A (no normal tests)")

    if result.categories:
        lines.append("\n── Category Breakdown ────────────────────────────────────")
        for cat in result.categories:
            bar = "●" * cat.passing + "○" * (cat.total - cat.passing)
            lines.append(
                f"  {cat.name:<20}  {cat.passing}/{cat.total}"
                f"  ({cat.pass_rate * 100:.0f}%)  {bar}"
            )

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def format_report(result: RobustnessResult) -> str:
    """Return a human-readable robustness evaluation report string."""
    return _format_report(result)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robustness_evaluator",
        description=(
            "Compute the ImpactGuard Composite Robustness Score (R) and "
            "Adversarial Fragility Index (F) from test-suite metrics."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--n-total", type=int, required=True, help="Total test count")
    p.add_argument(
        "--n-adversarial", type=int, required=True, help="Adversarial test count"
    )
    p.add_argument(
        "--passing-adv", type=int, required=True, help="Passing adversarial tests"
    )
    p.add_argument(
        "--passing-norm", type=int, required=True, help="Passing normal tests"
    )
    p.add_argument(
        "--coverage",
        type=float,
        required=True,
        help="Coverage ratio in [0.0, 1.0]",
    )
    p.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_ALPHA,
        help=(
            f"Adversarial weight in (0, 1).  Default: {DEFAULT_ALPHA} "
            "(security context).  Use 0.5 for general, 0.75 for red-team."
        ),
    )
    p.add_argument(
        "--categories",
        type=str,
        metavar="JSON",
        help=(
            "Per-category stats as JSON array, e.g. "
            '[{"name":"boundary","total":30,"passing":20}]'
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results as JSON instead of a human-readable report",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cats: list[CategoryStats] | None = None
    if args.categories:
        raw = json.loads(args.categories)
        cats = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Each category must be a JSON object")
            allowed = {
                k: v for k, v in item.items() if k in ("name", "total", "passing")
            }
            cats.append(CategoryStats(**allowed))

    try:
        # --- input bounds validation ---
        max_reasonable = 10_000_000
        for arg_name, arg_val in [
            ("n_total", args.n_total),
            ("n_adversarial", args.n_adversarial),
            ("passing_adv", args.passing_adv),
            ("passing_norm", args.passing_norm),
        ]:
            if arg_val >= max_reasonable:
                raise ValueError(
                    f"{arg_name} exceeds reasonable maximum {max_reasonable}"
                )

        result = evaluate_robustness(
            n_total=args.n_total,
            n_adversarial=args.n_adversarial,
            passing_adv=args.passing_adv,
            passing_norm=args.passing_norm,
            coverage=args.coverage,
            alpha=args.alpha,
            categories=cats,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.output_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(_format_report(result))

    # Output advisory info to stderr; exit code 0=success, non-zero=error
    if not result.meets_adversarial_minimum:
        print("Warning: adversarial minimum not met", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
