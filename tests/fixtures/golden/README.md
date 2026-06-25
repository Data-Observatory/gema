# Golden Dataset for Regression Testing

This directory holds the golden dataset used by `tests/test_regression.py` to verify
that `metagen` produces semantically equivalent outputs across code changes, prompt
edits, and dependency bumps.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `inputs/` | Sample input JSON files — start with `examples/*.json`, populate with real Chilean gov data later. |
| `expected/` | Pinned expected outputs, one `<input_stem>.json` per input. **Empty until user runs `make record-golden`.** |
| `cache/` | diskcache snapshot captured during recording. Allows regression tests to run without an API key. **Empty until user runs `make record-golden`.** |

## Recording Procedure

Populating `expected/` and `cache/` requires a ZAI API key. Run locally:

```bash
export ZAI_API_KEY=...           # or whichever provider is configured as default
make record-golden               # runs scripts/record_golden.py
git add tests/fixtures/golden    # commit the bundle
```

Re-record after: prompt edits, model upgrades, or dependency bumps that affect output shape.
