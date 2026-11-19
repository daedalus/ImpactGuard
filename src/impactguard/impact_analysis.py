import json
import sys
from typing import Any

from ._logging import get_logger
from .risk_model import exposure
from .runtime_intelligence import (
    build_runtime_index,
    load_runtime_observations,
    lookup_runtime_count,
)

_log = get_logger(__name__)


def required_positional(func: dict[str, Any]) -> int:
    """Count required positional arguments."""
    return sum(1 for a in func.get("positional", []) if not a.get("has_default"))


def total_positional(func: dict[str, Any]) -> int:
    """Count total positional arguments."""
    return len(func.get("positional", []))


def load_funcs(path: str) -> dict[str, dict[str, Any]]:
    """Load function signatures from JSON file."""
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in signatures file '{path}': {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(
            f"Signatures file '{path}': expected a JSON array, got {type(data).__name__}"
        )
    result: dict[str, dict[str, Any]] = {}
    for entry in data:
        if not isinstance(entry, dict) or "fqname" not in entry:
            continue
        result[entry["fqname"]] = entry
    return result



def load_calls(path: str) -> list[dict[str, Any]]:
    """Load call sites from JSON file."""
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in call sites file '{path}': {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(
            f"Call sites file '{path}': expected a JSON array, got {type(data).__name__}"
        )
    return [entry for entry in data if isinstance(entry, dict)]


# ── Transitive impact helpers ─────────────────────────────────────────────────


def build_call_graph(
    calls: list[dict[str, Any]],
    funcs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, set[str]]:
    """Build a callee → set-of-callers inverted call graph.

    Args:
        calls: List of call-site dicts (as returned by extract_calls / analyze_module).
        funcs: Optional signature map.  When given, callee and caller names
            are resolved to signature fqnames (``file.py:func``) so the graph
            can be walked starting from the fqnames reported by
            :func:`compare_signatures.compare`.

    Returns:
        Dict mapping each called function name to the set of functions that call it.
    """
    graph: dict[str, set[str]] = {}
    dotted = _dotted_keys(funcs) if funcs else None
    for call in calls:
        callee = call.get("fqname") or call.get("name", "")
        caller_identity = call.get("caller") or call.get("file", "")
        if funcs:
            if callee:
                callee = _resolve_target(callee, funcs, dotted) or callee
            if call.get("caller"):
                caller_identity = (
                    _resolve_target(caller_identity, funcs, dotted)
                    or caller_identity
                )
        if callee:
            graph.setdefault(callee, set()).add(caller_identity)
    return graph


def find_transitive_callers(
    directly_affected: set[str],
    call_graph: dict[str, set[str]],
    depth: int = 1,
) -> dict[str, int]:
    """Return functions transitively affected by *directly_affected* up to *depth* hops.

    Args:
        directly_affected: Set of fqnames with direct breaking changes.
        call_graph: Inverted call graph (callee → callers) from :func:`build_call_graph`.
        depth: Maximum number of hops to follow (1 = only direct callers).

    Returns:
        Dict mapping affected caller names to their hop distance (1-based).

    Note:
        Cycle-safe: the ``found`` dict acts as a visited set, so a cycle such
        as A → B → A will not cause infinite iteration — once a node is
        recorded in ``found`` it is never added to the next frontier again.
    """
    found: dict[str, int] = {}
    frontier = set(directly_affected)

    for hop in range(1, depth + 1):
        next_frontier: set[str] = set()
        for callee in frontier:
            for caller in call_graph.get(callee, set()):
                if caller not in found and caller not in directly_affected:
                    found[caller] = hop
                    next_frontier.add(caller)
        frontier = next_frontier
        if not frontier:
            break

    return found


# ── Core analysis ─────────────────────────────────────────────────────────────


def _fqname_to_runtime_key(fqname: str) -> str:
    """Convert signature fqname to runtime key format.

    Signature fqnames look like "module.py:func" or "path/to/file.py:Class.method".
    Runtime keys (from trace_calls.py) look like "module.func" or "path.to.module.Class.method".

    Converts "module.py:func" → "module.func" by removing .py extension and replacing : with .
    """
    if ":" in fqname:
        file_part, func_part = fqname.split(":", 1)
        # Convert file path to module path: remove .py, replace / with .
        module_part = file_part.replace("\\", "/").removesuffix(".py").replace("/", ".")
        return f"{module_part}.{func_part}"
    return fqname


def _load_runtime_data(runtime_path: str | None) -> dict[str, int]:
    """Load runtime observations, falling back to an empty index on error."""
    if not runtime_path:
        return {}

    try:
        return build_runtime_index(load_runtime_observations(runtime_path))
    except (json.JSONDecodeError, KeyError) as exc:
        _log.warning("Failed to parse runtime data from '%s': %s", runtime_path, exc)
        print(f"Warning: Failed to parse runtime data: {exc}", file=sys.stderr)
    except OSError as exc:
        _log.warning("Failed to read runtime data from '%s': %s", runtime_path, exc)
        print(f"Warning: Failed to read runtime data: {exc}", file=sys.stderr)
    return {}


def _dotted_keys(funcs: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Map each signature fqname to its dotted form (``path.module.func``)."""
    return {f: _fqname_to_runtime_key(f) for f in funcs}


def _resolve_target(
    target: str,
    funcs: dict[str, dict[str, Any]],
    dotted: dict[str, str] | None = None,
) -> str | None:
    """Resolve a call target against loaded signatures.

    Call sites name their target as ``func``, ``module.func`` or
    ``Class.method`` while signatures use ``path/module.py:func``.  Resolution
    order:

    1. exact fqname match;
    2. the signature's dotted form (``path.module.func``) equals or ends with
       ``.<target>`` — unique match only;
    3. method leaf-name match (``var.method`` with unknown ``var``) — unique
       match only.

    *dotted* is an optional precomputed :func:`_dotted_keys` map; pass it
    when resolving many targets against the same *funcs*.
    """
    if not target:
        return None
    if target in funcs:
        return target

    if dotted is None:
        dotted = _dotted_keys(funcs)
    suffix = "." + target
    matches = [f for f, key in dotted.items() if key == target or key.endswith(suffix)]
    if len(matches) == 1:
        return matches[0]

    if not matches:
        leaf = "." + target.split(".")[-1]
        matches = [
            f for f in funcs if "." in f.split(":")[-1] and f.endswith(leaf)
        ]
        if len(matches) == 1:
            return matches[0]
    if len(matches) > 1:
        _log.warning(
            "Ambiguous target resolution for '%s': multiple candidates found (%s). "
            "Skipping to avoid false positives.",
            target,
            ", ".join(matches[:5]),
        )
    return None


def _arity_problem(call: dict[str, Any], func: dict[str, Any]) -> str | None:
    """Return ``"missing args"``, ``"too many args"`` or *None* when compatible.

    Keyword arguments that name a positional parameter count towards
    satisfying it, so ``f(1, b=2)`` is compatible with ``def f(a, b)``.
    """
    # Python call extractors use ``starargs``/``kwargs_any``; others use
    # ``has_starargs``/``has_kwargs`` — accept both spellings.
    if (
        call.get("has_starargs")
        or call.get("has_kwargs")
        or call.get("starargs")
        or call.get("kwargs_any")
    ):
        return None
    positional = func.get("positional", [])
    argc = call.get("args", 0) or 0
    if argc > len(positional) and not func.get("vararg"):
        return "too many args"
    keywords = set(call.get("kwargs") or [])
    for param in positional[argc:]:
        if not param.get("has_default") and param.get("name") not in keywords:
            return "missing args"
    return None


def _risk_level_for_mismatch(
    argc: int, min_args: int, severity: float, exp: float
) -> str:
    """Return a risk label for an arity mismatch."""
    if argc < min_args:
        return "HIGH"
    if severity > 0.8 and exp > 0.1:
        return "HIGH"
    if severity > 0.5:
        return "MEDIUM"
    return "LOW"


def _build_issue(
    call: dict[str, Any],
    target: str,
    func: dict[str, Any],
    problem: str,
    runtime: dict[str, int],
    max_count: int,
) -> dict[str, Any]:
    """Build an issue record for a direct arity mismatch."""
    func_name = func.get("name", target)
    runtime_key = _fqname_to_runtime_key(target)
    count = lookup_runtime_count(runtime, target, func_name, runtime_key) or 1
    exp = exposure(count, max_count)
    missing = problem == "missing args"
    severity = 0.9 if missing else 0.3
    risk = "HIGH" if missing else _risk_level_for_mismatch(0, 0, severity, exp)
    return {
        "function": target,
        "risk": risk,
        "change": problem,
        "exposure": exp,
        "confidence": min(1.0, count / 100),
        "file": call.get("file", ""),
        "lineno": call.get("lineno", 0),
        "count": count,
        "transitive": False,
    }


def _append_transitive_issues(
    issues: list[dict[str, Any]],
    directly_affected: set[str],
    calls: list[dict[str, Any]],
    transitive_depth: int,
    funcs: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Append transitive callers to the issue list when enabled."""
    if transitive_depth <= 0 or not directly_affected:
        return

    call_graph = build_call_graph(calls, funcs)
    transitive = find_transitive_callers(
        directly_affected, call_graph, transitive_depth
    )
    for caller, hop in transitive.items():
        issues.append(
            {
                "function": caller,
                "risk": "LOW",
                "change": f"indirect impact (hop {hop})",
                "exposure": 0.0,
                "confidence": 0.0,
                "file": caller,
                "lineno": 0,
                "count": 0,
                "transitive": True,
                "hop": hop,
            }
        )



# ── Core analysis ─────────────────────────────────────────────────────────────


def _check_arity_match(call: dict[str, Any], func: dict[str, Any]) -> bool:
    """Return True when the call-site arity is compatible with the function signature."""
    return _arity_problem(call, func) is None


def analyze(
    sigs_path: str, calls_path: str, runtime_path: str | None = None
) -> list[dict[str, Any]]:
    """Analyze impact of signature changes on call sites.

    Args:
        sigs_path: Path to signatures JSON file.
        calls_path: Path to calls JSON file.
        runtime_path: Optional path to runtime data JSON.

    Returns:
        List of impact issues.  Each dict includes a ``"transitive"`` flag
        (``False`` for direct issues, ``True`` for indirect callers).
    """
    from .config import get as cfg_get

    transitive_depth: int = int(cfg_get("analysis", "transitive_depth", 0))

    funcs = load_funcs(sigs_path)
    calls = load_calls(calls_path)
    runtime = _load_runtime_data(runtime_path)

    # Get max count for exposure calculation
    max_count = max(runtime.values()) if runtime else 1

    issues: list[dict[str, Any]] = []
    directly_affected: set[str] = set()

    _log.debug(
        "Analyzing impact: %d signatures, %d call sites",
        len(funcs),
        len(calls),
    )

    dotted = _dotted_keys(funcs)
    for call in calls:
        raw_target = call.get("fqname", call.get("name", ""))
        target = _resolve_target(raw_target, funcs, dotted)
        if target is None:
            continue

        f = funcs[target]

        problem = _arity_problem(call, f)
        if problem is None:
            continue

        directly_affected.add(target)
        issues.append(_build_issue(call, target, f, problem, runtime, max_count))

    _append_transitive_issues(
        issues, directly_affected, calls, transitive_depth, funcs
    )

    _log.debug(
        "Impact analysis complete: %d direct issue(s), %d transitive",
        sum(1 for i in issues if not i.get("transitive")),
        sum(1 for i in issues if i.get("transitive")),
    )
    return issues


def detect_uncalled_changes(
    breaking_changes: list[str],
    funcs: dict[str, dict[str, Any]],
    calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find changed functions that have zero call sites.

    A function with a breaking change but no call sites is a blind spot:
    it may be called dynamically (``getattr``, decorators, ``__call__``,
    higher-order functions) where static analysis cannot see the caller.

    Returns a list of issue dicts (same shape as :func:`analyze`) with
    risk ``"UNKNOWN"`` and an explanatory ``change`` message.

    Args:
        breaking_changes: List of breaking change strings from
            :func:`compare_signatures.compare`, each like
            ``"REMOVED: file.py:func"``.
        funcs: Signature dict from :func:`load_funcs`.
        calls: Call-site list from :func:`load_calls`.

    Returns:
        Issues for changed functions with no observed call sites.
    """
    # Resolve every call target to a signature fqname so that calls naming
    # ``module.func`` / ``func`` match signatures keyed ``module.py:func``.
    called_targets: set[str] = set()
    dotted = _dotted_keys(funcs)
    for call in calls:
        target = call.get("fqname") or call.get("name", "")
        if not target:
            continue
        called_targets.add(target)
        resolved = _resolve_target(target, funcs, dotted)
        if resolved:
            called_targets.add(resolved)

    issues: list[dict[str, Any]] = []
    for bc in breaking_changes:
        parts = bc.split(": ", 1)
        if len(parts) < 2:
            continue
        fqname = parts[1].split()[0]
        if fqname not in funcs:
            continue
        if fqname in called_targets:
            continue
        issues.append(
            {
                "function": fqname,
                "risk": "UNKNOWN",
                "change": f"{parts[0]} — no call sites detected (possible dynamic dispatch blind spot)",
                "exposure": 0.0,
                "confidence": 0.0,
                "file": funcs[fqname].get("file", ""),
                "lineno": funcs[fqname].get("lineno", 0),
                "count": 0,
                "transitive": False,
                "no_call_sites": True,
            }
        )
    return issues


def analyze_main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 3:
        print(
            "Usage: python impact_analysis.py <signatures.json> <calls.json> [runtime.json]"
        )
        sys.exit(1)

    issues = analyze(
        sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None
    )

    # Output summary
    for level in ["HIGH", "MEDIUM", "LOW"]:
        level_issues = [
            i for i in issues if i["risk"] == level and not i.get("transitive")
        ]
        if level_issues:
            print(f"[{level}] {len(level_issues)} issues:")
            for i in level_issues[:5]:
                print(f"  {i['function']} -> {i['change']} (count: {i['count']})")

    transitive = [i for i in issues if i.get("transitive")]
    if transitive:
        print(f"\n[TRANSITIVE] {len(transitive)} indirectly affected callers")

    if any(i["risk"] == "HIGH" for i in issues):
        sys.exit(1)


#: Public alias for the CLI entry point (backward-compat and test access).
main = analyze_main
