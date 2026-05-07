import math

# Severity scores for different types of changes.
#
# Rationale (S × E × C model):
#   Values range from 0.0 (harmless) to 1.0 (guaranteed breakage).  They
#   represent the *worst-case* probability that a caller breaks if it has not
#   been updated.  The values below are calibrated against common Python API
#   patterns:
#
#   REMOVED (1.0) — function is gone; every caller breaks unconditionally.
#   REQUIRED (0.9) — new required positional/keyword argument; callers that
#       don't pass it raise TypeError at runtime.
#   POSITIONAL_REORDER / KWONLY_REMOVED (0.8) — positional callers break
#       silently (wrong values) or loudly (TypeError), equally severe.
#   *args/*kwargs_REMOVED (0.7) — callers passing extra positional/keyword
#       args break; callers that never used the variadic param are unaffected.
#   TYPE_CHANGED / DECORATOR_REMOVED (0.6) — semantics change; many callers
#       may break depending on how they use the return value or rely on the
#       decorator's side-effects.
#   RETURN_TYPE_CHANGED (0.5) — callers that inspect or unpack the return
#       value may break; pure call-and-ignore callers are unaffected.
#   DECORATOR_ADDED (0.1) — adds a layer around the function (e.g. caching,
#       auth check); only callers that depend on the raw callable break.
#   OPTIONAL (0.3) — existing required argument gains a default; callers
#       compiled against the old signature still work but the semantics may
#       differ if the default is non-trivial.
#   DEPRECATED_REMOVED (0.15) — scheduled removal after a deprecation period;
#       callers should already have migrated.
#   ADDED (0.1) — new optional argument or new function; existing callers
#       are unaffected.
#   TYPE_WIDENED / RETURN_TYPE_WIDENED (0.05) — accepts/returns more types
#       than before; existing callers continue to work with the narrower type.
#
# These constants can be overridden per-project via impactguard.toml:
#   [impactguard.severity_scores]
#   REMOVED = 0.95
SEVERITY_SCORES = {
    "REMOVED": 1.0,
    "REQUIRED": 0.9,
    "POSITIONAL_REORDER": 0.8,
    "KWONLY_REMOVED": 0.8,
    "*args_REMOVED": 0.7,
    "**kwargs_REMOVED": 0.7,
    "TYPE_CHANGED": 0.6,
    "DECORATOR_REMOVED": 0.6,
    "RETURN_TYPE_CHANGED": 0.5,
    "DECORATOR_ADDED": 0.1,  # Adding decorators is typically non-breaking (e.g. @lru_cache, @staticmethod)
    "OPTIONAL": 0.3,
    "ADDED": 0.1,
    "DEPRECATED_REMOVED": 0.15,
    "TYPE_WIDENED": 0.05,
    "RETURN_TYPE_WIDENED": 0.05,
}


def _effective_severity_scores() -> dict[str, float]:
    """Return severity scores, preferring any overrides from the config file."""
    try:
        from .config import get_config

        cfg = get_config()
        overrides: dict[str, float] = cfg.get("impactguard", {}).get(
            "severity_scores", {}
        )
        if overrides:
            merged = dict(SEVERITY_SCORES)
            merged.update(overrides)
            return merged
    except Exception:
        pass
    return SEVERITY_SCORES


def get_severity(change_type: str) -> float:
    scores = _effective_severity_scores()
    # Check longer/more-specific keys first to avoid substring false-matches
    # e.g. "RETURN TYPE CHANGED" must not match "TYPE CHANGED" prematurely.
    for key in sorted(scores, key=len, reverse=True):
        if key in change_type:
            return scores[key]
    return 0.5


def exposure(count: int, max_count: int) -> float:
    if count == 0:
        return 0
    return min(1.0, math.log(1 + count) / math.log(1 + max_count))


def confidence(samples: int, threshold: int = 100) -> float:
    return min(1.0, samples / threshold)


_UNCONDITIONAL_HIGH = frozenset({
    "REMOVED",
    "REQUIRED_POSITIONAL_ADDED",
    "REQUIRED_KWONLY_ADDED",
})


def _is_unconditional_high(change_type: str) -> bool:
    """Check if change_type is definitionally breaking regardless of exposure.

    Uses prefix matching to avoid false matches like "DEPRECATED_REMOVED"
    being caught by "REMOVED" substring matching.
    """
    for key in _UNCONDITIONAL_HIGH:
        if change_type.startswith(key):
            return True
    return False


def classify(
    severity: float, count: int, max_count: int, samples: int, lambda_: float = 1.0,
    change_type: str = ""
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
    
    # Unconditional HIGH for definitionally-breaking changes
    # Uses explicit allowlist with prefix matching to avoid false matches
    if _is_unconditional_high(change_type):
        exposure_val = exposure(count, max_count)
        return "HIGH", exposure_val, 1.0
    
    exposure_val = exposure(count, max_count)
    confidence_val = confidence(samples)
    
    if confidence_val < conf_threshold:
        return "UNKNOWN", exposure_val, confidence_val
    
    effective_severity = severity * lambda_
    
    if effective_severity > 0.8 and exposure_val > high_exp_min:
        return "HIGH", exposure_val, confidence_val
    
    if effective_severity > 0.5 and exposure_val > med_exp_min:
        return "MEDIUM", exposure_val, confidence_val
    
    return "LOW", exposure_val, confidence_val


def compute_risk(
    severity: float, exposure_val: float, confidence_val: float, lambda_: float = 1.0
) -> float:
    return severity * exposure_val * confidence_val * lambda_
