def compute_confidence(
    target_certainty: float, structural: float, semantic: float, complexity: float
) -> float:
    return target_certainty * structural * semantic * complexity


def classify(conf: float) -> str:
    if conf >= 0.75:
        return "HIGH"
    elif conf >= 0.4:
        return "MEDIUM"
    elif conf >= 0.2:
        return "LOW"
    else:
        return "UNKNOWN"


def get_target_certainty(
    file_match: bool, lineno_match: bool, name_only_match: bool
) -> float:
    if file_match and lineno_match:
        return 1.0
    elif name_only_match:
        return 0.5
    else:
        return 0.2


def get_structural_safety(change_type: str) -> float:
    if "default" in change_type.lower() or "optional" in change_type.lower():
        return 1.0
    elif "kwarg" in change_type.lower():
        return 0.8
    elif "positional" in change_type.lower():
        return 0.3
    return 0.5


def get_semantic_risk(change_type: str) -> float:
    if "required" in change_type.lower():
        return 0.6
    return 1.0


def get_complexity_penalty(
    is_multiline: bool,
    has_decorators: bool,
    has_complex_annotations: bool,
    is_nested: bool,
) -> float:
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


def classify_with_factors(
    target: float, structural: float, semantic: float, complexity: float
) -> tuple[str, dict[str, float]]:
    conf = compute_confidence(target, structural, semantic, complexity)
    level = classify(conf)
    return level, {
        "target": target,
        "structure": structural,
        "semantic": semantic,
        "complexity": complexity,
        "final": conf,
    }
