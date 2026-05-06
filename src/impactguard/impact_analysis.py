import json
import sys
from typing import Any

from .risk_model import exposure


def required_positional(func: dict[str, Any]) -> int:
    """Count required positional arguments."""
    return sum(1 for a in func.get("positional", []) if not a.get("has_default"))


def total_positional(func: dict[str, Any]) -> int:
    """Count total positional arguments."""
    return len(func.get("positional", []))


def load_funcs(path: str) -> dict[str, dict[str, Any]]:
    """Load function signatures from JSON file."""
    with open(path) as f:
        data: list[dict[str, Any]] = json.load(f)
    return {f["fqname"]: f for f in data}


def load_calls(path: str) -> list[dict[str, Any]]:
    """Load call sites from JSON file."""
    with open(path) as f:
        data: list[dict[str, Any]] = json.load(f)
    return data


# ── Transitive impact helpers ─────────────────────────────────────────────────


def build_call_graph(calls: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Build a callee → set-of-callers inverted call graph.

    Args:
        calls: List of call-site dicts (as returned by extract_calls / analyze_module).

    Returns:
        Dict mapping each called function name to the set of functions that call it.
    """
    graph: dict[str, set[str]] = {}
    for call in calls:
        callee = call.get("fqname") or call.get("name", "")
        caller_file = call.get("file", "")
        if callee:
            graph.setdefault(callee, set()).add(caller_file)
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

    # Load runtime data if provided
    runtime: dict[str, int] = {}
    if runtime_path:
        try:
            with open(runtime_path) as f_file:
                rt_data = json.load(f_file)
            runtime = {item["function"]: item.get("count", 1) for item in rt_data}
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Failed to parse runtime data: {e}", file=sys.stderr)
            runtime = {}

    # Get max count for exposure calculation
    max_count = max(runtime.values()) if runtime else 1

    issues: list[dict[str, Any]] = []
    directly_affected: set[str] = set()

    for call in calls:
        target = call.get("fqname", call.get("name", ""))

        if target not in funcs:
            # Try fallback matching
            matches = [f for f in funcs if f.endswith("." + target.split(".")[-1])]
            if len(matches) == 1:
                target = matches[0]
            else:
                continue

        f = funcs[target]

        if call.get("has_starargs") or call.get("has_kwargs"):
            continue

        min_args = required_positional(f)
        max_args = total_positional(f) if not f["vararg"] else float("inf")

        argc = call.get("args", 0)

        if argc < min_args or argc > max_args:
            func_name = f.get("name", target)
            count = runtime.get(f"{func_name}", 1)
            exp = exposure(count, max_count)

            severity = 0.9 if argc < min_args else 0.3
            risk_level = (
                "HIGH"
                if severity > 0.8 and exp > 0.1
                else "MEDIUM"
                if severity > 0.5
                else "LOW"
            )

            directly_affected.add(target)
            issues.append(
                {
                    "function": target,
                    "risk": risk_level,
                    "change": "missing args" if argc < min_args else "too many args",
                    "exposure": exp,
                    "confidence": min(1.0, count / 100),
                    "file": call.get("file", ""),
                    "lineno": call.get("lineno", 0),
                    "count": count,
                    "transitive": False,
                }
            )

    # ── Transitive impact ─────────────────────────────────────────────────────
    if transitive_depth > 0 and directly_affected:
        call_graph = build_call_graph(calls)
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
