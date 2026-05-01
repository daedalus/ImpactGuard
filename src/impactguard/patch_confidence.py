def compute_confidence(target_certainty, structural, semantic, complexity):
    return target_certainty * structural * semantic * complexity


def classify(conf):
    if conf >= 0.75:
        return "HIGH"
    elif conf >= 0.4:
        return "MEDIUM"
    elif conf >= 0.2:
        return "LOW"
    else:
        return "UNKNOWN"


def get_target_certainty(file_match, lineno_match, name_only_match):
    if file_match and lineno_match:
        return 1.0
    elif name_only_match:
        return 0.5
    else:
        return 0.2


def get_structural_safety(change_type):
    if "default" in change_type.lower() or "optional" in change_type.lower():
        return 1.0
    elif "kwarg" in change_type.lower():
        return 0.8
    elif "positional" in change_type.lower():
        return 0.3
    return 0.5


def get_semantic_risk(change_type):
    if "required" in change_type.lower():
        return 0.6
    return 1.0


def get_complexity_penalty(
    is_multiline, has_decorators, has_complex_annotations, is_nested
):
    penalty = 1.0
    if is_multiline:
        penalty *= 0.7
    if has_decorators:
        penalty *= 0.5
    if has_complex_annotations:
        penalty *= 0.5
    if is_nested:
        penalty *= 0.5
    return penalty


def classify_with_factors(T, S, R, C):
    conf = compute_confidence(T, S, R, C)
    level = classify(conf)
    return level, {
        "target": T,
        "structure": S,
        "semantic": R,
        "complexity": C,
        "final": conf,
    }
