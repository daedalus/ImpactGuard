import math

# Severity scores for different types of changes
SEVERITY_SCORES = {
    "REMOVED": 1.0,
    "REQUIRED POSITIONAL ADDED": 0.9,
    "POSITIONAL REORDER/RENAME": 0.8,
    "REQUIRED KWONLY ADDED": 0.9,
    "KWONLY REMOVED": 0.8,
    "*args REMOVED": 0.7,
    "**kwargs REMOVED": 0.7,
    "OPTIONAL POSITIONAL ADDED": 0.3,
    "OPTIONAL KWONLY ADDED": 0.3,
    "ADDED": 0.1,
}


def get_severity(change_type):
    for key, score in SEVERITY_SCORES.items():
        if key in change_type:
            return score
    return 0.5


def exposure(count, max_count):
    if count == 0:
        return 0
    return min(1.0, math.log(1 + count) / math.log(1 + max_count))


def confidence(samples, threshold=100):
    return min(1.0, samples / threshold)


def classify(severity, count, max_count, samples):
    E = exposure(count, max_count)
    C = confidence(samples)

    if C < 0.3:
        return "UNKNOWN", E, C

    if severity > 0.8 and E > 0.1:
        return "HIGH", E, C

    if severity > 0.5 and E > 0.01:
        return "MEDIUM", E, C

    return "LOW", E, C


def compute_risk(severity, exposure_val, confidence_val):
    return severity * exposure_val * confidence_val
