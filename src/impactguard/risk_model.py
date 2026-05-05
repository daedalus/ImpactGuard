import math

# Severity scores for different types of changes
SEVERITY_SCORES = {
    "REMOVED": 1.0,
    "REQUIRED": 0.9,
    "POSITIONAL REORDER": 0.8,
    "KWONLY REMOVED": 0.8,
    "*args REMOVED": 0.7,
    "**kwargs REMOVED": 0.7,
    "OPTIONAL": 0.3,
    "ADDED": 0.1,
}


def get_severity(change_type: str) -> float:
    for key, score in SEVERITY_SCORES.items():
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
    exposure_val = exposure(count, max_count)
    confidence_val = confidence(samples)

    if confidence_val < 0.3:
        return "UNKNOWN", exposure_val, confidence_val

    if severity > 0.8 and exposure_val > 0.1:
        return "HIGH", exposure_val, confidence_val

    if severity > 0.5 and exposure_val > 0.01:
        return "MEDIUM", exposure_val, confidence_val

    return "LOW", exposure_val, confidence_val


def compute_risk(severity: float, exposure_val: float, confidence_val: float) -> float:
    return severity * exposure_val * confidence_val
