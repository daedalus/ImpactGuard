from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._logging import get_logger
from .patch_confidence import classify_with_factors

_log = get_logger(__name__)

_SUPPORTED_CST_CHANGES = {
    "REQUIRED_POSITIONAL_ADDED",
    "REQUIRED_KWONLY_ADDED",
}


def _callable_leaf_name(fqname: str) -> str:
    name_part = fqname.split(":")[-1]
    return name_part.split(".")[-1]


def _sig_index(signatures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(sig.get("fqname", "")): sig
        for sig in signatures
        if isinstance(sig, dict) and sig.get("fqname")
    }


def _find_first_required_pos(arguments: list[Any], offset: int) -> str | None:
    added = arguments[offset:]
    required = [
        str(a.get("name", ""))
        for a in added
        if isinstance(a, dict) and not bool(a.get("has_default", False))
    ]
    return required[0] if required else None


def _find_first_required_kwonly(old_kw: list[Any], new_kw: list[Any]) -> str | None:
    old_names = {str(a.get("name", "")) for a in old_kw if isinstance(a, dict)}
    required = [
        str(a.get("name", ""))
        for a in new_kw
        if isinstance(a, dict)
        and str(a.get("name", "")) not in old_names
        and not bool(a.get("has_default", False))
    ]
    return required[0] if required else None


def _resolve_required_added_param(
    change_type: str, old_sig: dict[str, Any] | None, new_sig: dict[str, Any] | None
) -> str | None:
    if old_sig is None or new_sig is None:
        return None

    old_pos = old_sig.get("positional", [])
    new_pos = new_sig.get("positional", [])
    old_kw = old_sig.get("kwonly", [])
    new_kw = new_sig.get("kwonly", [])
    if not isinstance(old_pos, list) or not isinstance(new_pos, list):
        return None
    if not isinstance(old_kw, list) or not isinstance(new_kw, list):
        return None

    if change_type == "REQUIRED_POSITIONAL_ADDED":
        return _find_first_required_pos(new_pos, len(old_pos))

    if change_type == "REQUIRED_KWONLY_ADDED":
        return _find_first_required_kwonly(old_kw, new_kw)

    return None


def _param_from_raw_change(raw_change: str) -> str | None:
    arg_match = re.search(r"arg '([^']+)'", raw_change)
    if arg_match:
        return arg_match.group(1)
    tail = raw_change.split()[-1] if raw_change.split() else ""
    cleaned = tail.strip("()':,")
    return cleaned or None


def build_change_events(
    comparison: dict[str, Any],
    old_signatures: list[dict[str, Any]],
    new_signatures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build normalized change events from signature comparison output."""
    from .risk_gate import parse_change_line

    old_idx = _sig_index(old_signatures)
    new_idx = _sig_index(new_signatures)
    events: list[dict[str, Any]] = []

    for raw in comparison.get("breaking", []):
        raw_change = str(raw)
        parsed = parse_change_line(raw_change)
        if parsed is None:
            continue
        change_type = str(parsed["change"])
        fqname = str(parsed["function"])
        old_sig = old_idx.get(fqname)
        new_sig = new_idx.get(fqname)
        source_sig = new_sig or old_sig or {}

        param_name = _resolve_required_added_param(change_type, old_sig, new_sig)
        if param_name is None and change_type in _SUPPORTED_CST_CHANGES:
            param_name = _param_from_raw_change(raw_change)

        event: dict[str, Any] = {
            "change": change_type,
            "change_type": change_type,
            "function": fqname,
            "raw_change": raw_change,
            "file": str(source_sig.get("file", "")),
            "cst_supported": change_type in _SUPPORTED_CST_CHANGES and bool(param_name),
        }
        if param_name:
            event["param_name"] = param_name
        events.append(event)
    return events


def generate_fix_candidates(report_item: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate fix candidates from normalized risk/change metadata."""
    from .cst_patch import patch_function
    from .patch_generator import patch_add_default

    change_type = str(
        report_item.get("change_type") or report_item.get("change") or ""
    ).strip()
    if change_type not in _SUPPORTED_CST_CHANGES:
        return []

    func_name = str(report_item.get("function", "")).strip()
    param_name = str(report_item.get("param_name", "")).strip()
    file_path = str(report_item.get("file", "")).strip()
    if not file_path or not func_name or not param_name:
        return []

    source_path = Path(file_path)
    if not source_path.exists():
        return []

    # CST patching is Python-only; skip non-Python files
    if not file_path.endswith(".py"):
        fallback_patch = patch_add_default(
            {
                "file": file_path,
                "lineno": int(report_item.get("lineno", 0) or 0),
                "name": func_name,
            },
            param_name,
        )
        if not fallback_patch:
            return []
        level, factors = classify_with_factors(0.7, 0.8, 0.7, 1.0)
        return [
            {
                "type": "text_patch",
                "patch": fallback_patch,
                "function": func_name,
                "file": file_path,
                "param_name": param_name,
                "confidence": factors,
                "confidence_level": level,
                "auto_applicable": False,
                "error": "CST patching is Python-only; text patch provided instead",
            }
        ]

    source = source_path.read_text()
    cst_error: str | None = None
    patched, cst_error = patch_function(
        source, _callable_leaf_name(func_name), param_name
    )
    if patched and patched != source:
        level, factors = classify_with_factors(0.95, 0.95, 0.85, 1.0)
        return [
            {
                "type": "cst_patch",
                "patch": patched,
                "function": func_name,
                "file": file_path,
                "param_name": param_name,
                "confidence": factors,
                "confidence_level": level,
                "auto_applicable": level == "HIGH",
                "error": cst_error,
            }
        ]

    fallback_patch = patch_add_default(
        {
            "file": file_path,
            "lineno": int(report_item.get("lineno", 0) or 0),
            "name": func_name,
        },
        param_name,
    )
    if not fallback_patch:
        return []
    level, factors = classify_with_factors(0.7, 0.8, 0.7, 1.0)
    return [
        {
            "type": "text_patch",
            "patch": fallback_patch,
            "function": func_name,
            "file": file_path,
            "param_name": param_name,
            "confidence": factors,
            "confidence_level": level,
            "auto_applicable": False,
            "error": cst_error,
        }
    ]


def enrich_risk_with_fix_candidates(
    risk_items: list[dict[str, Any]],
    change_events: list[dict[str, Any]],
    *,
    generate_fixes: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach normalized metadata and fix candidates to risk items."""
    event_map = {
        (str(e.get("function", "")), str(e.get("change", ""))): e for e in change_events
    }
    enriched: list[dict[str, Any]] = []
    all_fixes: list[dict[str, Any]] = []

    for item in risk_items:
        updated = dict(item)
        key = (str(item.get("function", "")), str(item.get("change", "")))
        event = event_map.get(key, {})
        for field in (
            "change_type",
            "raw_change",
            "param_name",
            "file",
            "cst_supported",
        ):
            if field in event:
                updated[field] = event[field]

        fixes = generate_fix_candidates(updated) if generate_fixes else []
        updated["fix_candidates"] = fixes
        updated["patches"] = [f["patch"] for f in fixes if f.get("patch")]
        if fixes:
            all_fixes.extend(fixes)
        enriched.append(updated)
    return enriched, all_fixes


def apply_safe_fixes(risk_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply high-confidence CST fixes conservatively (one fix per file).

    Creates backup files (``*.bak``) before applying each fix so that
    changes can be reverted if needed.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in risk_items:
        for fix in item.get("fix_candidates", []):
            if not isinstance(fix, dict):
                continue
            if fix.get("type") != "cst_patch":
                continue
            if not bool(fix.get("auto_applicable", False)):
                continue
            file_path = str(fix.get("file", "")).strip()
            if not file_path:
                continue
            grouped.setdefault(file_path, []).append(fix)

    applied: list[dict[str, Any]] = []
    for file_path, fixes in grouped.items():
        if not file_path.endswith(".py"):
            _log.warning(
                "Skipping CST patch for non-Python file '%s'", file_path,
            )
            continue
        if len(fixes) != 1:
            continue
        fix = fixes[0]
        patch_content = fix.get("patch")
        if not isinstance(patch_content, str) or not patch_content:
            continue
        path = Path(file_path)
        if not path.exists():
            continue
        # Create backup before applying
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            backup_path.write_text(path.read_text())
        except OSError as exc:
            _log.warning("Failed to create backup for '%s': %s", file_path, exc)
            continue
        path.write_text(patch_content)
        applied.append(
            {
                "file": file_path,
                "backup": str(backup_path),
                "function": fix.get("function", ""),
                "type": fix.get("type", ""),
                "confidence_level": fix.get("confidence_level", ""),
            }
        )
    return applied
