## Function Signature Tracking

This repository maintains an automatically generated file:

```
.signatures.txt
```

which contains extracted Python function signatures across all tracked `.py` files.

### Purpose

- Provide a lightweight view of the project’s callable surface
- Make API changes visible in diffs
- Enable future tooling (API drift detection, compatibility checks)

---

## Implementation

Signature extraction is performed via:

```
extract_signatures.py
```

This uses Python’s `ast` module rather than regex to correctly handle:

- `async def`
- decorators
- multiline signatures
- type annotations and return types
- `*args`, `**kwargs`, keyword-only arguments

---

## Git Hook: post-commit

A `post-commit` hook updates `.signatures.txt` after each commit and creates a follow-up commit **only if the file changed**.

### Hook behavior

1. Collect tracked Python files:
   ```
   git ls-files '*.py'
   ```

2. Extract signatures:
   ```
   python3 extract_signatures.py ...
   ```

3. If `.signatures.txt` changed:
   - Stage the file
   - Create a new commit:
     ```
     Update function signatures
     ```

4. Prevent infinite recursion via:
   ```
   SKIP_SIGNATURE_HOOK=1
   ```

---

## Important Tradeoffs

### 1. Extra Commits
Each API change may produce an additional commit.

- Pros: explicit history of interface changes
- Cons: noisier commit graph

### 2. Rebases / Merges
Hooks run during history rewriting, which can:

- introduce unexpected commits
- require manual cleanup

### 3. CI/CD
Git hooks are not executed in most CI environments.

→ `.signatures.txt` consistency is **not guaranteed** unless explicitly checked.

---

## Alternative (Not Currently Used)

A `pre-commit` hook could:

- update `.signatures.txt`
- include it in the *same* commit

This avoids extra commits but couples working tree mutation with commit creation.

---

## Known Limitations

- Nested functions are included
- Class methods are included (not namespaced by class)
- Parsing failures silently skip files
- Requires Python ≥ 3.9 (`ast.unparse`)

---

## Future Directions

Potential extensions:

- Include class context (`ClassName.method`)
- Detect breaking vs non-breaking API changes
- Compare signatures across commits
- Integrate with CI for enforcement
