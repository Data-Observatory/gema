# Scripts

Helper scripts for development and data maintenance — flags for each one, one
section per script. For the `gema` CLI, `agents.yaml`/config fields, and which
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

Runs the full `gema` Pipeline against all input files in `tests/fixtures/golden/inputs/`
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

Runs the full `gema` Pipeline with REAL API calls (no cache replay) against all
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

**Judge provider is deliberately separate from production.** `--judge` takes a
`provider:model` spec (e.g. `zai-coding-plan:glm-5.3`), not a bare model name —
the judge always resolves its own provider this way rather than inheriting
`config/agents.yaml`'s `default_provider`, so scoring never competes for the
same account/quota as whatever model is being generated or compared. Defaults
for `--judge`, `--threshold`, and `--inputs`/`--expected` all come from
`config/eval.yaml` (repo root, shared by this script and `compare_models.py`/
`judge_models.py`) when not passed explicitly — see that file for the actual
defaults and how to change them.

**Usage:**

```bash
# Defaults from config/eval.yaml (judge, threshold, golden corpus paths)
uv run python scripts/run_live_eval.py

# Custom threshold + judge (provider:model)
uv run python scripts/run_live_eval.py --threshold 0.80 --judge zai-coding-plan:glm-5.3

# Verbose mode
uv run python scripts/run_live_eval.py -v

# All options
uv run python scripts/run_live_eval.py \
    --config config/agents.yaml \
    --inputs tests/fixtures/golden/inputs \
    --expected tests/fixtures/golden/expected \
    --reports-dir reports \
    --schema cdif-discovery \
    --judge zai-coding-plan:glm-5.3 \
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

Runs the real `gema` Pipeline (live LLM calls, and by default live ROR/ISNI/ORCID
enrichment) against one or more real inputs, and checks whether the output would
survive a human reviewer's sanity check before publishing: valid JSON, non-placeholder
titles/creators/dates, a real Abstract, subjects and topics, and every DOI/ROR/ISNI
found anywhere in the output validated against its real format — and, unless
`--no-resolve` is passed, looked up live against `doi.org`/`ror.org`/`isni.org` to
confirm it actually resolves.

**Note:** the PID checks (format + live resolution) also run automatically on
*every* `gema process` run now — see `validate_pids`/`validate_pids_live` in
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
| `-s, --schema` | config's `schema_name` (e.g. `cdif-discovery`) | Schema name — only affects output formatting (`OutputWriter`), not generation, which always follows the config |
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

## `curate_ror_isni.py`

Two modes, both never auto-applying anything a human hasn't decided on.

**Collect** — queries ROR's public API for candidate matches against every org
name in a ground-truth directory that doesn't already carry a ROR identifier,
and writes a review file. Each entry starts with `approved_ror_id`,
`approved_isni_id`, and `country` set to `null` — a human fills these in by
hand; nothing is auto-applied.

```bash
uv run python scripts/curate_ror_isni.py \
    --ground-truth-dir tests/fixtures/do_catalog/ground_truth \
    --output reports/do_catalog/ror_isni_review.json
```

**Promote** — once a human has filled in `approved_ror_id`/`approved_isni_id`
(and, only for a name that's genuinely ambiguous across countries,
`country`) on the entries they've reviewed, promotes just those into
`config/overrides.yaml` (see `enrichers/identifier_overrides.py`) — the
durable, human-curated store `IdentifierResolver` checks before any ROR/ISNI
network call. Merges by `(name, country)`, so re-running after further
review updates existing entries instead of duplicating them.

```bash
uv run python scripts/curate_ror_isni.py \
    --promote-from reports/do_catalog/ror_isni_review.json \
    --promote-to config/overrides.yaml
```

| Flag | Mode | Description |
|------|------|--------------|
| `--ground-truth-dir` | collect | Directory of ground-truth JSON files |
| `--output` | collect | Where the review file is written |
| `--limit` | collect | Cap orgs queried (e.g. smoke test) |
| `--promote-from` | promote | The reviewed review file |
| `--promote-to` | promote | `config/overrides.yaml` to write/update |

## `ab_eval_cdif_vs_datacite.py`

A/B diagnostic (spec §9 of `docs/codata_mcp_croissant_cdifspecs.md`). It checks whether
generating CDIF and then crosswalking to DataCite lost data compared with the old
DataCite-direct generation. Side A cache-replays the current pipeline over
`tests/fixtures/golden/inputs/` (dummy LLM keys, so zero LLM cost) and exports each result
through `exporters/datacite.py`. Side B is the frozen
`tests/fixtures/golden_datacite46_baseline/expected/`, which isn't re-run. Scores each
resource and field with `json_semantic_diff`. It still makes a few real ROR/ISNI/ORCID/doi.org
requests (identifier enrichment and DOI resolution aren't cached).

```bash
make ab-eval
uv run python scripts/ab_eval_cdif_vs_datacite.py --threshold 0.90 -v
```

| Flag | Default | Description |
|------|---------|-------------|
| `--threshold` | `0.85` | Similarity below which a resource is flagged |
| `-v`, `--verbose` | off | DEBUG logging |

**Exit codes:** 0 = every resource at/above threshold, 1 = at least one below. Treat this
as informational. The baseline predates several intentional CDIF shape changes, so low
overall scores are expected. Use the per-field breakdown to spot a field that went empty.

## `compare_models.py`

Structural (Jaccard-vs-ground-truth) comparison across `provider:model` specs, using the
`do_catalog` ground-truth adapter (`do_catalog_common.adapt_ground_truth`). Runs the real
pipeline once per model per input, which costs real API calls unless you pass
`--rescore-only`.

```bash
uv run python scripts/compare_models.py \
    --output-root reports/do_catalog/pilot \
    --models zai-coding-plan:glm-5.3,opencode:deepseek-v4-flash
```

| Flag | Default | Description |
|------|---------|-------------|
| `--ground-truth-dir` | `config/eval.yaml` `corpora.do_catalog.ground_truth_dir` | Ground-truth JSON directory |
| `--inputs-dir` | `config/eval.yaml` `corpora.do_catalog.inputs_dir` | Matching inputs directory |
| `--output-root` | required | Where outputs (`outputs/<label>/*.json`), `comparison_data.json`, and `structural_comparison.md` go |
| `--models` | `config/eval.yaml` `candidates` | Comma-separated `provider:model` specs |
| `--limit` | all | Cap number of inputs (smoke test) |
| `--enrich` | off | Force identifier enrichment on (already on via the shipped config) |
| `--rescore-only` | off | Re-score already-saved outputs instead of re-running the pipeline, at zero API cost |

## `judge_models.py`

LLM-as-judge scoring over `compare_models.py`'s **already-saved** outputs (no pipeline
re-run). It builds one judge client, fixed across all candidates, and records a per-input
error rather than silently substituting the fallback scorer when DeepEval's `GEval` fails.

```bash
uv run python scripts/judge_models.py --output-root reports/do_catalog/pilot \
    --models zai-coding-plan:glm-5.3,opencode:deepseek-v4-flash
```

| Flag | Default | Description |
|------|---------|-------------|
| `--ground-truth-dir` / `--inputs-dir` | `config/eval.yaml` `corpora.do_catalog` | Same as `compare_models.py` |
| `--output-root` | required | The same `--output-root` passed to `compare_models.py` |
| `--models` | `config/eval.yaml` `candidates` | Comma-separated `provider:model` specs |
| `--judge` | `config/eval.yaml` `judge` (`zai-coding-plan:glm-5.3`) | `provider:model` for the judge. Needs that provider's key (`ZAI_API_KEY` by default) |

## `render_comparison_report.py`

Renders a static, self-contained HTML truth-vs-output diff report from a
`compare_models.py` run. Each row is one (item, metric) with the truth value, actual value,
and score, worst items first. Stdlib only, no API calls.

```bash
uv run python scripts/render_comparison_report.py \
    --output-root reports/do_catalog/pilot \
    --ground-truth-dir tests/fixtures/do_catalog/ground_truth
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output-root` | required | A `compare_models.py` output root |
| `--ground-truth-dir` | required | Ground truth used for that run |
| `--report` | `<output-root>/comparison_report.html` | Output HTML path |

## `sample_corpus.py`

Samples a working subset from the `do-catalog-resources` S3 corpus into
`tests/fixtures/do_catalog/` (`--source-prefix main`, stratified by month, with a pilot
subset that is a strict subset of the full draw) or `tests/fixtures/do_catalog_orcid/`
(`--source-prefix orcid`, a DataCite-sourced slice rich in personal creators for the ORCID
path). Uses the AWS CLI via subprocess with profile `catalogo-admin`, and needs access to
that bucket.

```bash
uv run python scripts/sample_corpus.py --source-prefix main --target 100 --pilot-size 18 --seed 42
uv run python scripts/sample_corpus.py --source-prefix orcid --target 20 --seed 42
```

| Flag | Default | Description |
|------|---------|-------------|
| `--source-prefix` | required | `main` or `orcid` preset |
| `--target` | `100` | Total files to sample |
| `--pilot-size` | `18` | `main` only: pilot subset size |
| `--seed` | `42` | Random seed |
| `-v`, `--verbose` | off | Verbose logging |

## `generate_inputs.py`

Derives minimal `{url, title, description, publisher}` inputs from a directory of
ground-truth records, using `reverse_input.py`'s leak-proof extractor. `--self-check`
validates an existing inputs directory instead, asserting that no enrichment-target key
leaked in.

```bash
uv run python scripts/generate_inputs.py \
    --ground-truth-dir tests/fixtures/do_catalog/ground_truth \
    --inputs-dir tests/fixtures/do_catalog/inputs --fetch

uv run python scripts/generate_inputs.py --self-check \
    --inputs-dir tests/fixtures/do_catalog/inputs \
    --ground-truth-dir tests/fixtures/do_catalog/ground_truth
```

| Flag | Default | Description |
|------|---------|-------------|
| `--ground-truth-dir` | — | Ground-truth `*.json` directory (required to generate) |
| `--inputs-dir` | required | Where inputs are written (or read, with `--self-check`) |
| `--self-check` | off | Validate instead of generate |
| `--fetch` | off | Live-fetch each URL into `fetched_content` (best-effort, real network calls) |
| `--fetch-delay` | `0.5` | Seconds between fetches |

## `validate_ground_truth.py`

Structural validator for `do_catalog` ground-truth records. It catches mis-shaped identifier
entries (e.g. an organization name in `name_identifier` with the real ID buried in
`scheme_uri`). It checks shape only, not correctness. No API calls.

```bash
make validate-gt
uv run python scripts/validate_ground_truth.py tests/fixtures/do_catalog/ground_truth
```

## `generate_ground_truth_schema.py`

Dumps `DataCiteOutputModel`'s JSON Schema to `tests/fixtures/do_catalog/ground_truth.schema.json`,
for editor autocomplete while hand-editing ground truth or `metadata_template.json`. No
arguments.

```bash
uv run python scripts/generate_ground_truth_schema.py
```

## Library modules (not standalone scripts)

- **`do_catalog_common.py`**: `do_catalog`-specific ground-truth adaptation (top-level
  `roles` → `creators`, scheme-aware identifier matching) used by `compare_models.py` /
  `judge_models.py`.
- **`fetch_content.py`**: best-effort live URL fetch that fills `fetched_content` for
  `generate_inputs.py --fetch`.
- **`reverse_input.py`**: corpus-agnostic reverse-input extraction. Its `ALLOWED_KEYS`
  defines exactly which fields a generated input may carry, so an eval never leaks a field
  the pipeline is supposed to produce.
- **`eval_common.py`**: see below.

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
