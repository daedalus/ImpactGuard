"""JSON data contract validation for ImpactGuard.

Provides lightweight structural validators for all inter-module data formats
so that format drift or version mismatches are caught early at load time.

No external dependencies — validation uses plain Python structural checks.
"""

from typing import Any


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_list(data: object, label: str, errors: list[str]) -> bool:
    """Ensure *data* is a list; record an error and return False otherwise."""
    if not isinstance(data, list):
        errors.append(f"{label}: expected a JSON array, got {type(data).__name__}")
        return False
    return True


def _check_fields(
    item: dict[str, Any],
    required: list[str],
    label: str,
    idx: int,
    errors: list[str],
) -> None:
    """Check that all *required* keys are present in *item*."""
    for field in required:
        if field not in item:
            errors.append(f"{label}[{idx}]: missing required field '{field}'")


def _check_arg(arg: object, label: str, idx: int, errors: list[str]) -> None:
    """Validate a single argument dict within a signature."""
    if not isinstance(arg, dict):
        errors.append(f"{label}[{idx}]: argument entry must be an object")
        return
    _check_fields(arg, ["name", "has_default"], f"{label}[{idx}].arg", 0, errors)


# ── Public validators ─────────────────────────────────────────────────────────

_SIGNATURE_REQUIRED = ["fqname", "name", "positional", "kwonly", "vararg", "kwarg"]
_CALL_REQUIRED = ["name", "lineno"]
_RUNTIME_REQUIRED = ["function", "count"]
_RISK_REQUIRED = ["function", "risk", "change", "exposure", "confidence"]


def validate_signatures(data: object) -> tuple[bool, list[str]]:
    """Validate a signatures JSON payload.

    Args:
        data: Parsed JSON value (should be a list of signature dicts).

    Returns:
        ``(valid, errors)`` where *valid* is *True* when no errors were found
        and *errors* is the list of human-readable problem descriptions.
    """
    errors: list[str] = []
    if not _check_list(data, "signatures", errors):
        return False, errors

    data_list = list(data)  # type: ignore[arg-type]  # _check_list verified isinstance
    for i, item in enumerate(data_list):
        if not isinstance(item, dict):
            errors.append(f"signatures[{i}]: expected an object, got {type(item).__name__}")
            continue
        _check_fields(item, _SIGNATURE_REQUIRED, "signatures", i, errors)
        for arg in item.get("positional", []):
            _check_arg(arg, f"signatures[{i}].positional", i, errors)
        for arg in item.get("kwonly", []):
            _check_arg(arg, f"signatures[{i}].kwonly", i, errors)

    return len(errors) == 0, errors


def validate_calls(data: object) -> tuple[bool, list[str]]:
    """Validate a call-sites JSON payload.

    Args:
        data: Parsed JSON value (should be a list of call dicts).

    Returns:
        ``(valid, errors)`` tuple.
    """
    errors: list[str] = []
    if not _check_list(data, "calls", errors):
        return False, errors

    data_list = list(data)  # type: ignore[arg-type]  # _check_list verified isinstance
    for i, item in enumerate(data_list):
        if not isinstance(item, dict):
            errors.append(f"calls[{i}]: expected an object, got {type(item).__name__}")
            continue
        _check_fields(item, _CALL_REQUIRED, "calls", i, errors)

    return len(errors) == 0, errors


def validate_runtime(data: object) -> tuple[bool, list[str]]:
    """Validate a runtime-trace JSON payload.

    Args:
        data: Parsed JSON value (should be a list of ``{function, count}`` dicts).

    Returns:
        ``(valid, errors)`` tuple.
    """
    errors: list[str] = []
    if not _check_list(data, "runtime", errors):
        return False, errors

    data_list = list(data)  # type: ignore[arg-type]  # _check_list verified isinstance
    for i, item in enumerate(data_list):
        if not isinstance(item, dict):
            errors.append(f"runtime[{i}]: expected an object, got {type(item).__name__}")
            continue
        _check_fields(item, _RUNTIME_REQUIRED, "runtime", i, errors)
        count = item.get("count")
        if count is not None and not isinstance(count, (int, float)):
            errors.append(f"runtime[{i}].count: expected a number, got {type(count).__name__}")

    return len(errors) == 0, errors


def validate_risk_report(data: object) -> tuple[bool, list[str]]:
    """Validate a risk-report JSON payload.

    Args:
        data: Parsed JSON value (should be a list of risk-report dicts).

    Returns:
        ``(valid, errors)`` tuple.
    """
    valid_levels = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
    errors: list[str] = []
    if not _check_list(data, "risk_report", errors):
        return False, errors

    data_list = list(data)  # type: ignore[arg-type]  # _check_list verified isinstance
    for i, item in enumerate(data_list):
        if not isinstance(item, dict):
            errors.append(
                f"risk_report[{i}]: expected an object, got {type(item).__name__}"
            )
            continue
        _check_fields(item, _RISK_REQUIRED, "risk_report", i, errors)
        risk = item.get("risk")
        if risk is not None and risk not in valid_levels:
            errors.append(
                f"risk_report[{i}].risk: invalid value '{risk}'; "
                f"must be one of {sorted(valid_levels)}"
            )

    return len(errors) == 0, errors


_VALIDATORS = {
    "signatures": validate_signatures,
    "calls": validate_calls,
    "runtime": validate_runtime,
    "risk_report": validate_risk_report,
}


def validate(kind: str, data: object) -> tuple[bool, list[str]]:
    """Dispatch to the appropriate validator by *kind*.

    Args:
        kind: One of ``"signatures"``, ``"calls"``, ``"runtime"``,
            ``"risk_report"``.
        data: Parsed JSON payload to validate.

    Returns:
        ``(valid, errors)`` tuple.

    Raises:
        ValueError: When *kind* is not a recognised data format.
    """
    if kind not in _VALIDATORS:
        raise ValueError(
            f"Unknown data kind '{kind}'; valid options: {sorted(_VALIDATORS)}"
        )
    return _VALIDATORS[kind](data)
