# Golden Dataset for Regression Testing

This directory holds the golden dataset used by `tests/test_regression.py` (`make
test-regression`) to verify that `gema` produces semantically equivalent outputs across
code changes, prompt edits, and dependency bumps. Regression runs cache-replay the
committed LLM responses, so no API key is needed. Output must score ≥ 0.85 against
`expected/` with `json-semantic-diff`.

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `inputs/` | 6 input resources (`sample_input01.json` … `sample_input06.json`) |
| `expected/` | Recorded CDIF Discovery (JSON-LD) output, one `<input_stem>.json` per input |
| `cache/` | `cache.db`, the diskcache snapshot of every LLM response captured while recording. Replayed by the regression test and by `make ab-eval` |

Identifier enrichment and DOI/PID checks are not cached, so a regression run still makes a
few real ROR/ISNI/ORCID/doi.org requests. Only the LLM calls are replayed.

## Recording Procedure

`make record-golden` runs `scripts/record_golden.py` with `config/agents.yaml`. It requires
the API key of that config's `default_provider`, which is currently `opencode`
(`OPENCODE_API_KEY`), the provider every shipped agent uses:

```bash
export OPENCODE_API_KEY=...      # or put it in .env
make record-golden               # runs scripts/record_golden.py
git add tests/fixtures/golden    # commit the bundle
```

The recorded cache is written with a ~10-year TTL so the committed replay never expires.
Full flags: [`scripts/README.md`](../../../scripts/README.md#record_goldenpy).

Re-record after prompt edits, model upgrades, or dependency bumps that affect output shape.
