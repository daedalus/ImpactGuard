"""Protocol and ABC class-hierarchy analysis for ImpactGuard.

Detects which classes are abstract (Protocol / ABC) and which concrete classes
implement them.  When a method on an abstract base changes, every concrete
implementation is implicitly broken; this module provides the data to surface
those cascade effects in the comparison report.
"""

import ast
from pathlib import Path
from typing import Any

# ── Data structures ───────────────────────────────────────────────────────────

# {class_name: {"bases": [str, ...], "file": str,
#               "is_protocol": bool, "is_abc": bool,
#               "methods": [str, ...]}}
ClassInfo = dict[str, Any]
Hierarchy = dict[str, ClassInfo]


# ── AST helpers ───────────────────────────────────────────────────────────────


def _base_names(bases: list[ast.expr]) -> list[str]:
    """Return string names for each base class expression."""
    names: list[str] = []
    for base in bases:
        try:
            names.append(ast.unparse(base))
        except Exception:
            pass
    return names


def _is_abstract(base_names: list[str]) -> tuple[bool, bool]:
    """Return (is_protocol, is_abc) flags from base class names."""
    protocol_markers = {"Protocol", "typing.Protocol", "typing_extensions.Protocol"}
    abc_markers = {"ABC", "abc.ABC", "ABCMeta", "abc.ABCMeta"}
    is_protocol = any(b in protocol_markers for b in base_names)
    is_abc = any(b in abc_markers for b in base_names)
    return is_protocol, is_abc


# ── Public API ────────────────────────────────────────────────────────────────


def extract_class_hierarchy(files: list[str]) -> Hierarchy:
    """Parse Python files and build a class-hierarchy map.

    Args:
        files: List of Python source file paths.

    Returns:
        Dictionary mapping ``class_name`` → class-info dict with keys:

        * ``bases``: list of base-class name strings
        * ``file``: source file path
        * ``is_protocol``: *True* when the class inherits from ``Protocol``
        * ``is_abc``: *True* when the class inherits from ``ABC`` or ``ABCMeta``
        * ``methods``: list of method names defined directly on this class
    """
    hierarchy: Hierarchy = {}

    for file_path in files:
        path = Path(file_path)
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            bases = _base_names(node.bases)
            is_protocol, is_abc = _is_abstract(bases)

            methods: list[str] = []
            for child in ast.walk(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    # Only direct methods (not nested class methods)
                    methods.append(child.name)

            hierarchy[node.name] = {
                "bases": bases,
                "file": str(path),
                "is_protocol": is_protocol,
                "is_abc": is_abc,
                "methods": methods,
            }

    return hierarchy


def find_implementations(hierarchy: Hierarchy) -> dict[str, list[str]]:
    """Map each abstract class to the list of concrete classes implementing it.

    Args:
        hierarchy: Output of :func:`extract_class_hierarchy`.

    Returns:
        Dictionary ``{abstract_class_name: [concrete_class_name, ...]}``.
    """
    abstract_classes = {
        name
        for name, info in hierarchy.items()
        if info["is_protocol"] or info["is_abc"]
    }

    implementations: dict[str, list[str]] = {name: [] for name in abstract_classes}

    for class_name, info in hierarchy.items():
        if class_name in abstract_classes:
            continue  # skip the abstract class itself
        for base in info["bases"]:
            # Match by short name (last segment after '.')
            short = base.split(".")[-1]
            if base in abstract_classes:
                implementations[base].append(class_name)
            elif short in abstract_classes:
                implementations[short].append(class_name)

    return implementations


def get_cascade_changes(
    comparison: dict[str, list[str]],
    hierarchy: Hierarchy,
    implementations: dict[str, list[str]] | None = None,
) -> list[str]:
    """Produce cascade-impact messages for Protocol/ABC method changes.

    When a method on an abstract base class is changed or removed, every
    concrete implementation is implicitly affected.  This function generates
    ``CASCADE: <concrete_class>.<method>`` messages to surface that impact.

    Args:
        comparison: Output of :func:`compare_signatures.compare`.
        hierarchy: Output of :func:`extract_class_hierarchy`.
        implementations: Output of :func:`find_implementations`.  Computed
            automatically when *None*.

    Returns:
        List of cascade-impact message strings.
    """
    if implementations is None:
        implementations = find_implementations(hierarchy)

    cascade: list[str] = []

    all_changes = comparison.get("breaking", []) + comparison.get("nonbreaking", [])

    for change in all_changes:
        # Look for patterns like "REMOVED: some_file.py:MyProtocol.method"
        parts = change.split(": ", 1)
        if len(parts) < 2:
            continue
        fqname = parts[1].strip()

        # Extract class.method from fqname (format: "file:ClassName.method")
        name_part = fqname.split(":")[-1]
        if "." not in name_part:
            continue  # top-level function, not a method

        class_name, method_name = name_part.split(".", 1)
        info = hierarchy.get(class_name)
        if info is None:
            continue

        if not (info["is_protocol"] or info["is_abc"]):
            continue

        # Emit one cascade message per concrete implementation
        for concrete in implementations.get(class_name, []):
            cascade.append(
                f"CASCADE: {fqname} → {concrete}.{method_name} "
                f"(concrete implementation of {class_name})"
            )

    return sorted(set(cascade))
