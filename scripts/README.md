# Scripts

Helper scripts for development and data maintenance.

## `generate_iana_data.py`

Fetches the IANA Media Types XML registry and generates `data/iana_media_types.json`.

```bash
uv run python scripts/generate_iana_data.py
```

Output: `data/iana_media_types.json` with `types` dict and `name_lookup` for MIME type resolution.

No arguments. Internet connection required.

## `record_golden.py`

Runs the full `metagen` Pipeline against all input files in `tests/fixtures/golden/inputs/`
and records the expected outputs + cache snapshot.

**Prerequisites:**

1. An API key for the default provider configured in your pipeline config.
   Default is `OPENCODE_API_KEY` (from `config/agents.yaml`), but may vary.
   Set it in your shell or `.env` file:

   ```bash
   export OPENCODE_API_KEY=...
   # or
   export ZAI_API_KEY=...
   ```

2. Input files present in `tests/fixtures/golden/inputs/`. Three sample files are
   pre-populated from `examples/`. Add more real inputs before recording.

**Usage:**

```bash
# Default paths
uv run python scripts/record_golden.py

# Explicit paths
uv run python scripts/record_golden.py \
    --config config/agents.yaml \
    --inputs tests/fixtures/golden/inputs \
    --expected tests/fixtures/golden/expected \
    --cache-dir tests/fixtures/golden/cache

# Verbose mode
uv run python scripts/record_golden.py -v
```

**What it writes:**

| Destination | Content |
|-------------|---------|
| `tests/fixtures/golden/expected/<stem>.json` | One pinned JSON output per input (indent=2, ensure_ascii=False) |
| `tests/fixtures/golden/cache/` | diskcache snapshot of all LLM calls made during recording |

**When to re-run:** After prompt edits, model upgrades, or dependency bumps that may
affect output shape. Commit the resulting `expected/` + `cache/` bundle to enable
offline regression testing.

## `run_live_eval.py`

Runs the full `metagen` Pipeline with REAL API calls (no cache replay) against all
golden inputs, scores each output against the expected golden output using LLM-as-judge
(DeepEval `GEval` + per-field hand-rolled scorer), and writes a Markdown report.

**Prerequisites:**

1. An API key for the default provider. Same as `record_golden.py`:
   ```bash
   export ZAI_API_KEY=...
   # or OPENCODE_API_KEY, OPENAI_API_KEY, etc.
   ```

2. Golden expected outputs populated by `record_golden.py`:
   ```bash
   uv run python scripts/record_golden.py  # or: make record-golden
   ```

**Usage:**

```bash
# Default paths, threshold 0.75
uv run python scripts/run_live_eval.py

# Custom threshold + judge model
uv run python scripts/run_live_eval.py --threshold 0.80 --model glm-5.2

# Verbose mode
uv run python scripts/run_live_eval.py -v

# All options
uv run python scripts/run_live_eval.py \
    --config config/agents.yaml \
    --inputs tests/fixtures/golden/inputs \
    --expected tests/fixtures/golden/expected \
    --reports-dir reports \
    --schema datacite-4.6 \
    --model glm-5.2 \
    --threshold 0.75 \
    --verbose
```

**What it writes:**

| Destination | Content |
|-------------|---------|
| `reports/live_eval_<timestamp>.md` | Per-input scores, per-field breakdown, overall summary, PASS/FAIL |

**Exit codes:** 0 = PASS, 1 = FAIL, 2 = env not configured.

**When to re-run:** Pre-release, after prompt edits, after model upgrades, after major
refactors. NOT needed for every commit — the regression test suite (Phase 3) covers
structural changes without API costs.
