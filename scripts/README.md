# Scripts

Helper scripts for development and data maintenance — flags for each one, one
section per script. For the `metagen` CLI, `agents.yaml`/config fields, and which
test tier to reach for, see [`../docs/CONFIGURATION.md`](../docs/CONFIGURATION.md)
instead — that content isn't duplicated here.

## `generate_iana_data.py`

Fetches the IANA Media Types XML registry and generates `src/metadata_enricher/data/iana_media_types.json`.

```bash
uv run python scripts/generate_iana_data.py
```

Output: `src/metadata_enricher/data/iana_media_types.json` with `types` dict and `name_lookup` for MIME type resolution.

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
(DeepEval `GEval` + per-field hand-rolled scorer, both from `eval_common.py` — see
above), and writes a Markdown report.

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
uv run python scripts/run_live_eval.py --threshold 0.80 --model glm-5.3

# Verbose mode
uv run python scripts/run_live_eval.py -v

# All options
uv run python scripts/run_live_eval.py \
    --config config/agents.yaml \
    --inputs tests/fixtures/golden/inputs \
    --expected tests/fixtures/golden/expected \
    --reports-dir reports \
    --schema datacite-4.6 \
    --model glm-5.3 \
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

## `validate_real_output.py`

Runs the real `metagen` Pipeline (live LLM calls, and by default live ROR/ISNI/ORCID
enrichment) against one or more real inputs, and checks whether the output would
survive a human reviewer's sanity check before publishing: valid JSON, non-placeholder
titles/creators/dates, a real Abstract, subjects and topics, and every DOI/ROR/ISNI
found anywhere in the output validated against its real format — and, unless
`--no-resolve` is passed, looked up live against `doi.org`/`ror.org`/`isni.org` to
confirm it actually resolves.

**Note:** the PID checks (format + live resolution) also run automatically on
*every* `metagen process` run now — see `validate_pids`/`validate_pids_live` in
[`../docs/CONFIGURATION.md`](../docs/CONFIGURATION.md). This script shares that
same logic (`enrichers/pid_validator.py`) but adds the structural/content checks
(titles, abstract, subjects, topics) and a detailed batch report on top — reach
for it when you want the full human-reviewer-style report for a specific run, not
just the pass-through warnings a normal `process` run surfaces.

This is not the golden/regression suite (which replays cached responses, no API
calls) and not `run_live_eval.py` (which asks an LLM judge how semantically close the
output is to a reference). This script checks concrete, checkable facts about one
real run.

**Prerequisites:** same as `record_golden.py` — an API key for the default provider.

**Usage:**

```bash
# Single file (default: examples/sample_input01.json)
uv run python scripts/validate_real_output.py
uv run python scripts/validate_real_output.py --input examples/sample_input02.json

# A batch from a directory (first 5 files)
uv run python scripts/validate_real_output.py --input-dir tests/fixtures/golden/inputs --limit 5

# Format-only PID checks, no live doi.org/ror.org/isni.org calls
uv run python scripts/validate_real_output.py --no-resolve

# Force real API calls instead of the on-disk LLM cache
uv run python scripts/validate_real_output.py --fresh-cache

# Save the raw output JSON alongside the report
uv run python scripts/validate_real_output.py --output-dir reports/real_validation/outputs
```

| Flag | Default | Description |
|------|---------|--------------|
| `--input` | `examples/sample_input01.json` | Single input JSON file |
| `--input-dir` | — | Directory of input files instead of a single `--input` |
| `--limit` | `3` | Max files to process from `--input-dir` |
| `-c, --config` | `config/agents.yaml` | Pipeline config YAML |
| `-s, --schema` | `datacite-4.6` | Schema name |
| `--no-enrich` | off | Disable ROR/ISNI/ORCID identifier enrichment (default follows the config) |
| `--no-resolve` | off | Skip live PID lookups — format regex/checksum only |
| `--fresh-cache` | off | Bypass the on-disk LLM cache for this run |
| `--output-dir` | — | Write each input's raw output JSON here |
| `--reports-dir` | `reports/real_validation` | Where the Markdown report is written |
| `-v, --verbose` | off | DEBUG logging |

**What it writes:**

| Destination | Content |
|-------------|---------|
| `reports/real_validation/validation_<timestamp>.md` | Per-input check table + every PID found with format/resolution status |
| `<output-dir>/<stem>.json` (if `--output-dir` given) | Raw pipeline output per input |

**Exit codes:** 0 = no FAIL anywhere (WARN still passes), 1 = at least one FAIL,
2 = environment not configured or no input files found.

## `eval_common.py`

Not a standalone script — shared, corpus-agnostic evaluation infrastructure imported
by the other scripts on this page and by whichever corpus-specific comparison/judge
scripts exist under `scripts/` (see the do_catalog eval harness). Two concerns live
here:

1. **Pipeline execution for an arbitrary `provider:model` spec** — `parse_model_spec`,
   `sanitize_label`, `run_pipeline_for_model` (retries flaky reasoning-model responses
   up to 3 times, keeping whichever attempt had the highest field coverage), and
   `MODEL_EXTRA_BODY` — a lookup table of confirmed provider/model request-body
   overrides (e.g. `{"thinking": {"type": "disabled"}}` for models that default to a
   "thinking mode" incompatible with Instructor's forced `tool_choice` — confirmed for
   `deepseek-v4-flash`/`deepseek-v4-pro`/`qwen3.7-plus` this way; never assumed by
   analogy for an untested model).
2. **Scoring an actual output against a ground truth** — structurally
   (`extract_creator_names`, `extract_ror_ids`, `extract_geo_places`, etc., `jaccard`,
   `compare_outputs`, `WEIGHTS` — 9 weighted metrics: creator names, ROR match rate,
   subjects, categories, rights, languages, geo places, media formats, field coverage)
   or semantically (`score_overall_deepeval` — DeepEval `GEval` judge — and
   `score_per_field_raw` — a hand-rolled per-field LLM-as-judge via `complete_raw()`).

Nothing in this module assumes a fixed input/ground-truth directory or a specific
ground-truth JSON shape — callers pass paths and already-unwrapped/adapted dicts.
`run_live_eval.py` (below) and any corpus-specific comparison script both build on
this rather than duplicating it.
