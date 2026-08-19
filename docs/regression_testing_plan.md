# Regression & Reproducibility Testing Plan for `gema`

**Created:** 2026-06-23
**Status:** Approved by user; executing autonomously
**Pinned model:** `glm-5.3` from `zai-coding-plan` provider (GLM 5.5 does not exist yet)
**API key constraint:** ZAI key is LOCAL ONLY — never uploaded to CI/cloud

## Goal

Verify `gema` produces **comparable (semantically similar)** outputs across runs, prompt edits, model upgrades, and dependency bumps. NOT exact-match reproducibility — temperature=0 + seed gets close, but GPU non-determinism means we use **semantic similarity ≥ 0.85** as the regression bar.

---

## Phases

### Phase 0 — Wire `process` CLI (T22) — DONE

The `process` command at `cli.py:139-202` is fully wired. It loads config, calls `Pipeline.run(input_source, pattern)`, routes successful results to `OutputWriter.write(document, output_path)`, logs per-resource errors to stderr without stopping the batch, and exits 1 only when all resources fail. All existing flags (`--output/-o`, `--schema/-s`, `--config/-c`) preserved. Verified by `tests/test_cli.py::TestProcessCommand` (5 tests, all green).

### Phase 1 — Determinism Primitives

**Problem:** `cache.py:_make_key` hashes `prompt:model:response_model_name` only. Temperature and seed are NOT in the key, so swapping models or temps can return stale cached outputs. Also no seed field exists anywhere.

**Changes:**

| File | Change |
|------|--------|
| `config/models.py` | Add `seed: int \| None = None` to `ProviderConfig` |
| `llm/base.py` | Add `seed: int \| None = None` to `LLMConfig` |
| `llm/factory.py` | Thread `seed` from `ProviderConfig` → `LLMConfig` |
| `llm/instructor_client.py` | Pass seed via `extra_body={"seed": seed}` when not None (both `complete` + `complete_raw`) |
| `cache.py` | Include `temperature` + `seed` in `_make_key` hash input (breaking cache change — accept cold cache) |
| `tests/test_seed_propagation.py` | New file — spy on `instructor_client.chat.completions.create` and assert seed + temp reach the wire |

**Risk:** ZAI/GLM-5.2 seed support is unknown. If the API rejects `extra_body.seed`, Phase 1.3 falls back to cache-only determinism (document this in the test).

### Phase 2 — Golden Dataset Infrastructure

**Cannot be run autonomously — requires user's ZAI API key.**

**Deliverable:** Empty scaffold + recorder script the user runs locally once.

| Path | Purpose |
|------|---------|
| `tests/fixtures/golden/inputs/` | Sample input JSON files (start with `examples/*.json`, add 15+ real Chilean gov resources later) |
| `tests/fixtures/golden/expected/` | Pinned outputs `<input_stem>.json` (one per input) |
| `tests/fixtures/golden/cache/` | diskcache snapshot (committed, ~200KB for 20×5 calls) |
| `scripts/record_golden.py` | CLI tool — runs `Pipeline` with `model=glm-5.3`, `seed=<cfg>`, `temperature=0`, writes `expected/` + snapshots cache |

**Recording procedure (user runs locally):**

```bash
export ZAI_API_KEY=...        # from .env
make record-golden            # runs scripts/record_golden.py
git add tests/fixtures/golden # commit outputs + cache bundle
```

Re-record after: prompt edits, model upgrades, dependency bumps that affect output shape.

### Phase 3 — Regression Harness (CI-friendly, no API key needed)

Replays committed cache bundle against current code; compares output to `expected/` using **`json-semantic-diff`**.

| Change | Detail |
|--------|--------|
| `pyproject.toml` | Add `json-semantic-diff>=0.1.0` to dev extras |
| `pyproject.toml` | Add `regression` marker alongside `live` |
| `tests/test_regression.py` | New file — iterates `fixtures/golden/inputs/*.json`, replays via cache, asserts `json_semantic_diff.score(actual, expected) >= 0.85` per sample with per-field breakdown in failure messages |
| `tests/test_regression.py` | `pytest.skip_if_no_fixtures` — graceful skip when `expected/` is empty (pre-recording) |

**Run:** `make test-regression` → `uv run pytest tests/test_regression.py -m regression`

### Phase 4 — Live Evaluator (local-only, real API) ✅ IMPLEMENTED

For pre-release scoring, prompt-edit validation, model upgrade checks, and major refactor validation.
Runs the Pipeline with real API calls (no cache replay), scores actual output against golden
expected output using LLM-as-judge, and writes a Markdown report.

**Scorer:** DeepEval `GEval` v4.0.7 (primary, overall semantic quality) + hand-rolled
per-field LLM-as-judge using the same judge model via `complete_raw()` (per-field breakdown + notes).
DeepEval was chosen because it installed/imported cleanly; the hand-rolled supplement provides
field-level granularity that GEval alone cannot produce.

| File | Purpose |
|------|---------|
| `scripts/run_live_eval.py` | CLI script — arg-driven, mirrors `record_golden.py` style |
| `reports/live_eval_<timestamp>.md` | Per-run report with per-input scores, per-field breakdown, summary |
| `.gitignore` | `reports/` added (gitignored) |
| `pyproject.toml` | `deepeval>=4.0.0` in dev extras |

**Key arguments:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--config/-c` | `config/agents.yaml` | Pipeline config (providers + agents) |
| `--inputs/-i` | `tests/fixtures/golden/inputs` | Input JSON files to evaluate |
| `--expected/-e` | `tests/fixtures/golden/expected` | Golden expected outputs |
| `--model` | `glm-5.3` | Judge LLM model (may differ from production model) |
| `--threshold` | `0.75` | PASS/FAIL threshold for mean score |
| `--schema/-s` | `datacite-4.6` | Schema name |
| `--verbose/-v` | off | DEBUG logging |

**Exit codes:** 0 = PASS (mean ≥ threshold), 1 = FAIL, 2 = env not configured.

**Scoring flow per input:**
1. DeepEval `GEval` — compares actual vs expected JSON given resource description as context, returns overall score + reason.
2. Hand-rolled `complete_raw()` call — prompts the judge LLM for per-field accuracy/completeness/coherence scores + qualitative notes (JSON response).
3. Overall score prefers DeepEval, falls back to hand-rolled if DeepEval fails.
4. Fallback: if JSON parsing fails on the per-field call, a simple structural field-overlap comparison is used.

**Example invocation:**

```bash
export ZAI_API_KEY=...     # or whichever provider is default
make record-golden          # populate expected/ first (prerequisite)

# Run live eval
uv run python scripts/run_live_eval.py -v
uv run python scripts/run_live_eval.py --threshold 0.80 --model glm-5.3
```

**Cadence:**

| Trigger | Rationale |
|---------|-----------|
| **Pre-release** | Catch quality regressions before tagging |
| **After prompt edits** | Verify prompt changes don't degrade semantic quality |
| **After model upgrades** | Compare new model quality against golden baseline |
| **After major refactors** | Ensure pipeline changes preserve output quality |

### Phase 5 — Tooling & Config Updates

| File | Change |
|------|--------|
| `Makefile` | Add `test-regression`, `record-golden`, `live-eval` targets |
| `config/providers.yaml` | Set `zai-coding-plan` to `default: true`, others `false` |
| `config/agents.yaml` | Pin every agent's `model:` to `glm-5.3`; add `seed: 42` to `zai-coding-plan` provider |

### Phase 6 — Diff Visualization (SKIPPED, bonus)

Not in scope for this autonomous run.

---

## Three-Tier Verification Strategy

| Tier | Cadence | Cost | What it catches |
|------|---------|------|-----------------|
| **T1 — Unit (mock)** | Every commit | $0 | Control-flow regressions, type errors, contract violations |
| **T2 — Regression (cache-replay)** | Every PR | $0 | Output-shape regressions, semantic drift vs golden |
| **T3 — Live eval (real API)** | Pre-release | $ (ZAI) | Quality regressions only detectable by scoring |

---

## Critical Risks

1. **ZAI/GLM-5.2 seed support unknown** — Phase 1.3 smoke-tests. Fallback: cache-only determinism (works because cache key includes seed after Phase 1.4).
2. **Cache key change is breaking** — old `~/.cache/gema/` entries won't match new keys. Document `make clean-cache` procedure.
3. **json-semantic-diff is young** — if it lacks features, fallback to `structeval` or hand-rolled Jaccard/cosine on field sets.
4. **Prompt changes invalidate cache** — document re-record procedure prominently.

---

## When You Come Back

Read this file top-to-bottom. Then:

1. `make test` — verify Phase 0-1 changes pass
2. `make test-regression` — should SKIP (no fixtures yet)
3. Populate `tests/fixtures/golden/inputs/` with 15+ real Chilean gov JSON inputs.
   Three example inputs (`sample_input01..03.json`) are already pre-populated from `examples/`.
4. Set the API key for your default provider, then run the recorder:

   ```bash
   # Check which provider is default in config/agents.yaml (default_provider field)
   export OPENCODE_API_KEY=...   # or ZAI_API_KEY, OPENAI_API_KEY, etc.
   make record-golden            # runs scripts/record_golden.py
   ```

   This generates `expected/` + `cache/` bundle.
5. `git add tests/fixtures/golden && git commit`
6. `make test-regression` — now runs and should PASS
7. (Optional) `make live-eval` — produces `reports/live_eval_<ts>.md`

If Phase 1.3 seed fails against the provider: edit `scripts/record_golden.py` to remove
`extra_body.seed`, re-record. Cache key still differs by seed field so multi-seed runs
stay isolated.
