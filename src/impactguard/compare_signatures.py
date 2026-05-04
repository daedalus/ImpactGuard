import json
import sys
from typing import Any


def load(path: str) -> dict[str, dict[str, Any]]:
    """Load signatures from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return {f["fqname"]: f for f in data}


def is_required(arg: dict[str, Any]) -> bool:
    """Check if a function argument has a default value."""
    return not arg["has_default"]


def compare(old_path: str, new_path: str) -> dict[str, list[str]]:  # noqa: MC0001
    """Compare two signature snapshots.

    Args:
        old_path: Path to old signatures JSON.
        new_path: Path to new signatures JSON.

    Returns:
        Dictionary with 'breaking' and 'nonbreaking' lists.
    """
    old = load(old_path)
    new = load(new_path)

    breaking: list[str] = []
    nonbreaking: list[str] = []

    # Removed functions
    for k in old:
        if k not in new:
            breaking.append(f"REMOVED: {k}")

    # Added functions
    for k in new:
        if k not in old:
            nonbreaking.append(f"ADDED: {k}")

    # Compare shared
    for k in old:
        if k not in new:
            continue

        o = old[k]
        n = new[k]

        o_pos = o["positional"]
        n_pos = n["positional"]

        # positional argument removal
        if len(n_pos) < len(o_pos):
            breaking.append(f"POSITIONAL REMOVED: {k}")
            continue

        # positional arg changes
        for i in range(len(o_pos)):
            if o_pos[i]["name"] != n_pos[i]["name"]:
                breaking.append(f"POSITIONAL REORDER/RENAME: {k}")
                break

        # new positional args
        if len(n_pos) > len(o_pos):
            added = n_pos[len(o_pos) :]
            if any(is_required(a) for a in added):
                breaking.append(f"REQUIRED POSITIONAL ADDED: {k}")
            else:
                nonbreaking.append(f"OPTIONAL POSITIONAL ADDED: {k}")

        # kwonly args
        o_kw = {a["name"]: a for a in o["kwonly"]}
        n_kw = {a["name"]: a for a in n["kwonly"]}

        for name in o_kw:
            if name not in n_kw:
                breaking.append(f"KWONLY REMOVED: {k}")

        for name in n_kw:
            if name not in o_kw:
                if is_required(n_kw[name]):
                    breaking.append(f"REQUIRED KWONLY ADDED: {k}")
                else:
                    nonbreaking.append(f"OPTIONAL KWONLY ADDED: {k}")

        # varargs changes
        if o["vararg"] and not n["vararg"]:
            breaking.append(f"*args REMOVED: {k}")

        if o["kwarg"] and not n["kwarg"]:
            breaking.append(f"**kwargs REMOVED: {k}")

    return {"breaking": sorted(set(breaking)), "nonbreaking": sorted(set(nonbreaking))}


def main() -> None:
    """CLI entry point for compare command."""
    if len(sys.argv) < 3:
        print("Usage: python compare_signatures.py <old.json> <new.json>")
        sys.exit(1)

    result = compare(sys.argv[1], sys.argv[2])

    print("=== BREAKING ===")
    print("\n".join(result["breaking"]) or "None")

    print("\n=== NON-BREAKING ===")
    print("\n".join(result["nonbreaking"]) or "None")

    if result["breaking"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
