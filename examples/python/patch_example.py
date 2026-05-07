#!/usr/bin/env python3
"""
ImpactGuard Patch Example

This script demonstrates how to use ImpactGuard's patching utilities:
1. difflib-based patch generation (patch_generator)
2. CST-based patching with libcst (cst_patch)
3. Patch confidence scoring (patch_confidence)

The example uses the old/main.py and new/main.py files to simulate
a scenario where a function parameter was removed (breaking change).
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from impactguard.cst_patch import patch_call, patch_function
from impactguard.patch_confidence import (
    classify,
    compute_confidence,
    get_complexity_penalty,
    get_semantic_risk,
    get_structural_safety,
    get_target_certainty,
)


def example_difflib_patch() -> None:
    """Example 1: Demonstrate difflib-based patch concept."""
    print("=" * 60)
    print("Example 1: difflib-based patch (patch_generator)")
    print("=" * 60)

    # Note: patch_generator uses is_safe_path() which rejects absolute paths.
    # For this example, we'll demonstrate the difflib concept directly.

    old_source = """def add(a: int, b: int) -> int:
    return a + b
"""

    new_source = """def add(a: int, b: int = None) -> int:
    return a + b
"""

    print("\nOriginal function:")
    print(old_source)
    print("Patched function (with default):")
    print(new_source)

    print("\n--- Generated unified diff ---")
    import difflib

    diff = difflib.unified_diff(
        old_source.splitlines(keepends=True),
        new_source.splitlines(keepends=True),
        fromfile="a/old_main.py",
        tofile="b/new_main.py",
    )

    print("".join(diff))

    print("\nNote: patch_generator.py adds defaults to function definitions")
    print("and patches call sites. It validates paths for security.")


def example_cst_patch() -> None:
    """Example 2: Generate a CST-based patch using libcst."""
    print("\n" + "=" * 60)
    print("Example 2: CST-based patch (cst_patch with libcst)")
    print("=" * 60)

    old_file = Path(__file__).parent / "old" / "main.py"
    source = old_file.read_text()

    print(f"\nOriginal source ({old_file.name}):")
    print(source)

    print("\n--- Patching function to add default value ---")
    patched, error = patch_function(source, "add", "b")

    if patched:
        print("\nPatched source:")
        print(patched)

        # Show the diff
        import difflib

        diff = difflib.unified_diff(
            source.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile="original",
            tofile="patched",
        )
        print("\nDiff:")
        print("".join(diff))
    else:
        print(f"Error: {error}")

    print("\n--- Patching call sites ---")
    patched_calls, error = patch_call(source, "add", "b")

    if patched_calls:
        print("\nPatched calls:")
        print(patched_calls)
    else:
        print(f"Error: {error}")


def example_patch_confidence() -> None:
    """Example 3: Calculate patch confidence score."""
    print("\n" + "=" * 60)
    print("Example 3: Patch Confidence Scoring")
    print("=" * 60)

    # Scenario: Patching a function to add default value
    target = get_target_certainty(
        file_match=True, lineno_match=True, name_only_match=False
    )
    structural = get_structural_safety("add_default")
    semantic = get_semantic_risk("optional_parameter")
    complexity = get_complexity_penalty(
        is_multiline=False,
        has_decorators=False,
        has_complex_annotations=False,
        is_nested=False,
    )

    print(f"\nTarget certainty: {target}")
    print(f"Structural safety: {structural}")
    print(f"Semantic risk: {semantic}")
    print(f"Complexity penalty: {complexity}")

    confidence = compute_confidence(target, structural, semantic, complexity)
    level = classify(confidence)

    print(f"\nFinal confidence score: {confidence:.3f}")
    print(f"Confidence level: {level}")

    # Another scenario: Complex function
    print("\n--- Scenario 2: Complex function ---")
    target = get_target_certainty(
        file_match=True, lineno_match=False, name_only_match=True
    )
    structural = get_structural_safety("positional_change")
    semantic = get_semantic_risk("required_parameter")
    complexity = get_complexity_penalty(
        is_multiline=True,
        has_decorators=True,
        has_complex_annotations=True,
        is_nested=False,
    )

    confidence = compute_confidence(target, structural, semantic, complexity)
    level = classify(confidence)

    print(f"Confidence score: {confidence:.3f}")
    print(f"Confidence level: {level}")


def example_full_workflow() -> None:
    """Example 4: Full workflow - detect change and generate patch."""
    print("\n" + "=" * 60)
    print("Example 4: Full Workflow (Detect + Patch)")
    print("=" * 60)

    old_file = Path(__file__).parent / "old" / "main.py"

    old_source = old_file.read_text()

    print("\nDetected changes:")
    print("  - Function 'add' removed parameter 'b' (breaking change)")
    print("  - Call site at line 8 needs update")

    print("\nRecommended fixes:")
    print("  1. Add default value to parameter 'b' in function definition")
    print("  2. Update call sites to handle missing parameter")

    # Generate the CST patch
    print("\n--- Generated CST Patch ---")
    patched, error = patch_function(old_source, "add", "b")

    if patched:
        print("\nFixed function definition:")
        print(patched)
    else:
        print(f"Error: {error}")


def main() -> None:
    """Run all examples."""
    print("\n🔒 ImpactGuard Patch Generation Examples\n")

    try:
        example_difflib_patch()
    except Exception as e:
        print(f"Error in difflib example: {e}")

    try:
        example_cst_patch()
    except Exception as e:
        print(f"Error in CST example: {e}")

    example_patch_confidence()
    example_full_workflow()

    print("\n" + "=" * 60)
    print("✅ All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
