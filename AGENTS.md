## Function Signature Tracking

This repository uses automatic signature tracking across all tracked `.py` files.

### Purpose

- Provide a lightweight view of the project's callable surface
- Make API changes visible in diffs
- Enable future tooling (API drift detection, compatibility checks)

---

## Implementation

Signature extraction is performed via:

```
extract_signatures.py
```

This uses Python's `ast` module rather than regex to correctly handle:

- `async def`
- decorators
- multiline signatures
- type annotations and return types
- `*args`, `**kwargs`, keyword-only arguments

---

## Git Hook: post-commit

A `post-commit` hook runs signature extraction after each commit.

### Hook behavior

1. Collect tracked Python files:
   ```
   git ls-files '*.py'
   ```

2. Extract signatures:
   ```
   impactguard extract <files> > /tmp/impactguard_sigs.json
   ```

3. Hook runs silently (no auto-commit):
   - Extraction is for tracking/debugging purposes
   - No automatic commit of signature files

4. Prevent infinite recursion via:
   ```
   SKIP_SIGNATURE_HOOK=1
   ```

---

## Important Tradeoffs

### 1. Rebases / Merges
Hooks run during history rewriting, which can:

- introduce unexpected behavior
- require manual cleanup

### 2. CI/CD
Git hooks are not executed in most CI environments.

→ Signature tracking is **not guaranteed** unless explicitly checked.

---

## Alternative (Not Currently Used)

A `pre-commit` hook could:

- extract signatures
- include them in the *same* commit

This avoids extra commits but couples working tree mutation with commit creation.

---

## Known Limitations

- Nested functions are included
- Class methods now include class context (`ClassName.method`)
- Parsing failures silently skip files
- Requires Python ≥ 3.9 (`ast.unparse`)

---

## Additional Tools

### Runtime Tracing

- `trace_calls.py` — low-overhead runtime call tracer
- `trace_calls_prod.py` — production sampler with configurable `SAMPLE_RATE`
- Aggregates call counts across test/prod runs

### Risk Analysis

- `risk_model.py` — computes risk as `S × E × C` (severity × exposure × confidence)
- `risk_gate.py` — combines diff + runtime data into structured JSON report
- `enforce_gate.py` — CI gate: blocks on HIGH, warns on UNKNOWN

### Reporting & Fixes

- `generate_report.py` — static HTML report from risk JSON
- `suggest_fixes.py` — generates fix suggestions with call-site locations
- `patch_generator.py` — diff-based patch previews using `difflib`
- `cst_patch.py` — CST-based patches using `libcst` (preserves formatting)
- `patch_confidence.py` — scores patch confidence per-multiplying target × structural × semantic × complexity

### CI Integration

- `.github/workflows/ci.yml` — GitHub Actions workflow with:
  - Signature extraction + comparison
  - Runtime data aggregation
  - Risk analysis + HTML report generation
  - Enforcement gate
  - **Changelog generation** from signature diffs

---

## Future Directions

Potential extensions:

- Detect breaking vs non-breaking API changes
- Compare signatures across commits
- Integrate with CI for enforcement
- **Feedback loop** — learn from patch acceptance/rejection to calibrate confidence
