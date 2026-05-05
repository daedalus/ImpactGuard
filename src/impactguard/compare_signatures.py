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


def _is_public(fqname: str) -> bool:
    """Return True if the function name (last segment) is public (no leading _)."""
    name_part = fqname.split(":")[-1]
    # For class methods like ClassName.method, check the method part
    leaf = name_part.split(".")[-1]
    return not leaf.startswith("_")


def compare(  # noqa: MC0001
    old_path: str,
    new_path: str,
    include_private: bool | None = None,
) -> dict[str, list[str]]:
    """Compare two signature snapshots.

    Args:
        old_path: Path to old signatures JSON.
        new_path: Path to new signatures JSON.
        include_private: When *False* (default from config), functions whose
            leaf name starts with ``_`` are excluded from comparison.  Pass
            *True* to include them.

    Returns:
        Dictionary with 'breaking' and 'nonbreaking' lists.
    """
    from .config import get as cfg_get

    if include_private is None:
        include_private = bool(cfg_get("analysis", "include_private", False))

    old = load(old_path)
    new = load(new_path)

    # Filter private symbols unless explicitly included
    if not include_private:
        old = {k: v for k, v in old.items() if _is_public(k)}
        new = {k: v for k, v in new.items() if _is_public(k)}

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
        else:
            # positional arg changes
            for i in range(len(o_pos)):
                if o_pos[i]["name"] != n_pos[i]["name"]:
                    breaking.append(f"POSITIONAL REORDER/RENAME: {k}")
                    break

            # new positional args
            if len(n_pos) > len(o_pos):
                added = n_pos[len(o_pos):]
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

        # ── Type annotation changes (new in this version) ──────────────────

        # Per-argument type changes
        for i, (o_arg, n_arg) in enumerate(zip(o_pos, n_pos)):
            o_type = o_arg.get("type")
            n_type = n_arg.get("type")
            if o_type is not None and n_type is not None and o_type != n_type:
                breaking.append(f"TYPE CHANGED: {k} arg '{o_arg['name']}' {o_type} -> {n_type}")

        for o_arg_name, o_arg in o_kw.items():
            if o_arg_name in n_kw:
                o_type = o_arg.get("type")
                n_type = n_kw[o_arg_name].get("type")
                if o_type is not None and n_type is not None and o_type != n_type:
                    breaking.append(
                        f"TYPE CHANGED: {k} kwarg '{o_arg_name}' {o_type} -> {n_type}"
                    )

        # Return type changes
        o_ret = o.get("return_type")
        n_ret = n.get("return_type")
        if o_ret is not None and n_ret is not None and o_ret != n_ret:
            breaking.append(f"RETURN TYPE CHANGED: {k} {o_ret} -> {n_ret}")

        # ── Decorator changes (new in this version) ────────────────────────
        o_decs = set(o.get("decorators", []))
        n_decs = set(n.get("decorators", []))
        for removed_dec in o_decs - n_decs:
            breaking.append(f"DECORATOR REMOVED: {k} @{removed_dec}")
        for added_dec in n_decs - o_decs:
            # Adding a decorator is usually breaking (changes calling convention)
            breaking.append(f"DECORATOR ADDED: {k} @{added_dec}")

    return {"breaking": sorted(set(breaking)), "nonbreaking": sorted(set(nonbreaking))}
