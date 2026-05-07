# ImpactGuard Patch Examples

This directory contains examples demonstrating how to use ImpactGuard's patching utilities.

## `impactguard compare` Command

The `compare` command now supports two modes:

### Default Mode (Source Files)
By default, `impactguard compare` treats arguments as source files and automatically extracts signatures:

```bash
# Compare two source files directly
impactguard compare old_file.py new_file.py

# With output
impactguard compare old_file.py new_file.py -o results.json
```

This wires the extract logic inside compare - no need to manually run `extract` first.

### JSON Mode
Use `--json` flag to compare pre-extracted JSON signature files:

```bash
# Compare two JSON signature files
impactguard compare --json old_sigs.json new_sigs.json

# Or use the short form
impactguard compare --json old.json new.json -o results.json
```

## `impactguard semver` Command

The `semver` command also supports both modes:

```bash
# Default: compare source files
impactguard semver old_file.py new_file.py

# JSON mode
impactguard semver --json old_sigs.json new_sigs.json --current-version 1.2.3
```

## `impactguard check` Command with `--suggest-patch`

The `check` command (and related commands) now supports `--suggest-patch` flag to generate patches:

```bash
# Generate patches for suggested fixes
impactguard check --suggest-patch old_file.py new_file.py

# With other check commands
impactguard check-diff --suggest-patch diff.patch
impactguard check-commit --suggest-patch HEAD
impactguard check-commits --suggest-patch v1.0 v1.1
```

When `--suggest-patch` is used:
- Patches are generated for each suggested fix
- Patches are saved to `patches/` directory in the output directory
- The command output shows the generated patches with file paths

Example output:
```
=== Generated Patches (2) ===
  - patch_1: cst_patch patch
    File: /tmp/impactguard_xxx/patches/patch_1.py
  - patch_2: cst_patch patch
    File: /tmp/impactguard_xxx/patches/patch_2.py
```

## Running the Example

```bash
cd /path/to/ImpactGuard
python examples/python/patch_example.py
```

## What the Example Demonstrates

### Example 1: difflib-based Patching
Shows how `patch_generator.py` creates unified diffs using Python's `difflib`. This is a text-based approach that works on source code as strings.

### Example 2: CST-based Patching
Demonstrates `cst_patch.py` which uses `libcst` (Concrete Syntax Tree) to make modifications while preserving original formatting. This is the preferred method for generating patches.

Key classes:
- `AddDefaultTransformer` - Adds default values to function parameters
- `FixCallTransformer` - Injects missing keyword arguments at call sites

### Example 3: Patch Confidence Scoring
Shows how `patch_confidence.py` calculates a confidence score for patches based on:
- **Target certainty** - How well we identified the target (file, line, name)
- **Structural safety** - How safe the change is structurally
- **Semantic risk** - Risk based on the type of change
- **Complexity penalty** - Penalties for decorators, annotations, nesting, etc.

Confidence levels:
- `HIGH` (≥ 0.75)
- `MEDIUM` (≥ 0.4)
- `LOW` (≥ 0.2)
- `UNKNOWN` (< 0.2)

### Example 4: Full Workflow
Demonstrates a complete workflow of detecting API changes and generating appropriate patches.

## Integration with ImpactGuard

These patching utilities are used by:
- `suggest_fixes.py` - Generates fix suggestions with call-site locations
- `risk_gate.py` - Combines diff + runtime data into structured JSON report
- CI workflow (`.github/workflows/ci.yml`) - Generates patches as part of the enforcement gate

## Notes

- `patch_generator.py` validates file paths for security (rejects absolute paths and traversal)
- `cst_patch.py` requires `libcst` to be installed (`pip install libcst`)
- The `FIXME` placeholder in call-site patches should be replaced with appropriate values
