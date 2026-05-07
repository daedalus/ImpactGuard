#!/usr/bin/env python3
"""
ImpactGuard Patch Command Example

This script demonstrates how to use the `impactguard patch` CLI command
to generate and apply patches for API breaking changes.
"""

import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: str, description: str) -> subprocess.CompletedProcess[str]:
    """Run a command and print the output."""
    print(f"\n{'=' * 60}")
    print(f"$ {description}")
    print(f"{'=' * 60}")
    print(f"$ {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result


def main() -> None:
    """Demonstrate impactguard patch command."""
    base = Path(__file__).parent
    old_file = base / "old" / "main.py"
    new_file = base / "new" / "main.py"

    print("\n🔒 ImpactGuard `patch` Command Example\n")

    # Show the difference between old and new
    print("=" * 60)
    print("Step 1: Understanding the API Change")
    print("=" * 60)
    print("\nOld version (old/main.py):")
    print(old_file.read_text())
    print("New version (new/main.py):")
    print(new_file.read_text())

    print("\n" + "=" * 60)
    print("Step 2: Extract Signatures")
    print("=" * 60)
    run_cmd(
        f"impactguard extract {old_file} > /tmp/old_sigs.json",
        "Extract signatures from old version",
    )
    run_cmd(
        f"impactguard extract {new_file} > /tmp/new_sigs.json",
        "Extract signatures from new version",
    )

    print("\n" + "=" * 60)
    print("Step 3: Compare Signatures")
    print("=" * 60)
    run_cmd(
        "impactguard compare /tmp/old_sigs.json /tmp/new_sigs.json",
        "Compare signatures to find changes",
    )

    print("\n" + "=" * 60)
    print("Step 4: Using `impactguard patch` Command")
    print("=" * 60)

    # Patch function definition - add default value
    run_cmd(
        f"impactguard patch {old_file} add b --type function",
        "Patch function: add default value to parameter 'b'",
    )

    # Patch call sites
    run_cmd(
        f"impactguard patch {old_file} add b --type call",
        "Patch call sites: add missing parameter 'b'",
    )

    # Output to file
    run_cmd(
        f"impactguard patch {old_file} add b --type function --output /tmp/patched_main.py",
        "Output patched file to /tmp/patched_main.py",
    )

    print("\n" + "=" * 60)
    print("Step 5: Apply Patch In-Place")
    print("=" * 60)
    print("\nCreating a copy to demonstrate --apply flag...")
    subprocess.run(f"cp {old_file} /tmp/test_main.py", shell=True)
    run_cmd(
        "impactguard patch /tmp/test_main.py add b --type function --apply",
        "Apply patch in-place to /tmp/test_main.py",
    )
    run_cmd("cat /tmp/test_main.py", "Show patched file contents")

    print("\n" + "=" * 60)
    print("Step 6: Full Check Pipeline")
    print("=" * 60)
    run_cmd(f"impactguard check {old_file} {new_file}", "Run full check pipeline")

    print("\n" + "=" * 60)
    print("✅ All examples completed!")
    print("=" * 60)
    print("\nKey takeaways:")
    print("  - `impactguard patch <file> <func> <param> --type function`")
    print("    Adds a default value to a function parameter")
    print("  - `impactguard patch <file> <func> <param> --type call`")
    print("    Adds missing argument to call sites")
    print("  - Use `--output` to write to a file")
    print("  - Use `--apply` to modify the source file in-place")


if __name__ == "__main__":
    main()
