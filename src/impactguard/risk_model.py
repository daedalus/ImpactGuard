import math

# Severity scores for different types of changes (defaults — overridable via config)
SEVERITY_SCORES = {
    "REMOVED": 1.0,
    "REQUIRED": 0.9,
    "POSITIONAL REORDER": 0.8,
    "KWONLY REMOVED": 0.8,
    "*args REMOVED": 0.7,
    "**kwargs REMOVED": 0.7,
    "TYPE CHANGED": 0.6,
    "DECORATOR REMOVED": 0.6,
    "RETURN TYPE CHANGED": 0.5,
    "DECORATOR ADDED": 0.4,
    "OPTIONAL": 0.3,
    "ADDED": 0.1,
}


def _effective_severity_scores() -> dict[str, float]:
    """Return severity scores, preferring any overrides from the config file."""
    try:
        from .config import get as cfg_get
        overrides: dict[str, float] = cfg_get("severity_scores", None) or {}  # type: ignore[assignment]
        if overrides:
            merged = dict(SEVERITY_SCORES)
            merged.update(overrides)
            return merged
    except Exception:
        pass
    return SEVERITY_SCORES


def get_severity(change_type: str) -> float:
    scores = _effective_severity_scores()
    for key, score in scores.items():
        if key in change_type:
            return score
    return 0.5


def exposure(count: int, max_count: int) -> float:
    if count == 0:
        return 0
    return min(1.0, math.log(1 + count) / math.log(1 + max_count))


def confidence(samples: int, threshold: int = 100) -> float:
    return min(1.0, samples / threshold)


def classify(
    severity: float, count: int, max_count: int, samples: int
) -> tuple[str, float, float]:
    try:
        from .config import get as cfg_get
        conf_threshold: float = cfg_get("risk", "confidence_threshold", 0.3)
        high_exp_min: float = cfg_get("risk", "high_exposure_min", 0.1)
        med_exp_min: float = cfg_get("risk", "medium_exposure_min", 0.01)
    except Exception:
        conf_threshold = 0.3
        high_exp_min = 0.1
        med_exp_min = 0.01

    exposure_val = exposure(count, max_count)
    confidence_val = confidence(samples)

    if confidence_val < conf_threshold:
        return "UNKNOWN", exposure_val, confidence_val

    if severity > 0.8 and exposure_val > high_exp_min:
        return "HIGH", exposure_val, confidence_val

    if severity > 0.5 and exposure_val > med_exp_min:
        return "MEDIUM", exposure_val, confidence_val

    return "LOW", exposure_val, confidence_val


def compute_risk(severity: float, exposure_val: float, confidence_val: float) -> float:
    return severity * exposure_val * confidence_val
