# Backlog

Deferred, non-urgent improvements surfaced during development — not tracked
elsewhere (no issue tracker in use for this repo). Each item should carry
enough context to pick up cold; prune entries once actually done.

## Agents / prompts

- **Grounded lookup tool for agents (web search or a static gazetteer
  function-call), instead of relying on the model's parametric knowledge.**
  `creators_publishers`'s hardcoded Chile-ministry→affiliation lookup table
  only covers ~15 agencies; anything else, the model guesses from memory,
  ungrounded. Real fix needs actual tool-calling (Instructor/OpenAI function
  calling), not a prompt tweak. Same underlying gap as the DOI-resolver idea
  below — nothing in this pipeline can currently "look things up," every
  agent call is a stateless completion over whatever text is in the prompt.
- **Split `core_metadata` into two agents** (identified during the 2026-08-11
  prompt review, not implemented). It's twice the size of any other agent
  (9 reasoning steps, 9 output fields) and its weakest-quality fields
  (`geo_locations`, `temporal_events`, `alternate_identifiers`,
  `related_identifiers`) sit at the end, where a cheap model's instruction-
  following is weakest. Candidate split: keep `core_metadata` for
  resource/titles/descriptions/languages/dates, add a new agent for
  geo/temporal/alternate+related identifiers. Config-only change
  (`depends_on: []` either way, so no orchestration risk) but costs
  wall-clock at `max_workers: 1` — weigh against the quality gain, or at
  minimum reorder the existing prompt so the highest-value fields sit
  closest to the appended resource data.
- **DOI-resolver enricher**: for DOI-identified resources, fetch real
  Crossref/DataCite metadata to backfill weak/missing fields, instead of
  relying purely on LLM extraction from title/description text. Flagged
  out of scope during the do_catalog eval work.

## Identifier enrichment

- **Curated, human-reviewed ROR/ISNI ground truth** to replace the messy
  source data (do_catalog's raw VIAF/Wikidata/malformed-ISNI identifiers
  aren't reliable as strict ROR-only ground truth — the eval's scoring
  adapter works around this with scheme-aware matching, but the underlying
  source data quality issue is untouched).

## Pipeline / infra

- **`config/providers.yaml` is a visor-only preset pool, not dead** (corrects
  an earlier "dead/orphaned, delete-or-wire-in" note). It's read by
  `visor/bootstrap.py:load_providers_pool_safe()`, which only feeds Settings'
  "Add a provider" autofill picker — never wired into pipeline execution,
  never edited. Runtime provider config for both the CLI and visor is still
  `config/agents.yaml` (same `find_config()`/`load_config()` path for both).
  No functional gap between CLI and visor here: adding a provider by hand-
  editing `config/agents.yaml`'s `providers:` list achieves the exact same
  end state visor's picker does — the pool is a UX nicety (autofill), not a
  capability. Evaluated and rejected: plumbing `providers.yaml` into the
  pipeline itself — nothing to wire in, since visor doesn't feed it into
  execution either. Only real option, low priority: a `metagen
  list-known-providers` CLI command reading the same pool, purely for
  discoverability parity of the autofill convenience — not urgent.
- **`max_workers` bump when production model moves off zai-coding-plan.**
  Currently pinned to 1 (`4101ac9`) because that provider's account rate
  limit is tight (429s even at `max_workers=2`). Confirmed empirically this
  session: `opencode:deepseek-v4-flash` handles `max_workers=5` with zero
  429s, ~3x wall-clock speedup per resource (18.7s vs ~57s summed). Safe to
  raise only if/when the default provider actually changes — don't touch it
  while still on glm-5.2.
- **`mimo-v2.5` dropped from the eval model set** (decision, 2026-08-11): a
  content-dense DOI resource (`136`, GFZ dataset, 6000-char fetched_content)
  caused a 3244s (54min) stall for mimo-v2.5 vs. 1201s for glm-5-turbo on the
  same eval run — too unreliable to keep as a production candidate. Eval/prod
  model set going forward: `glm-5.2`, `glm-5-turbo`, `deepseek-v4-flash`.
- **Real production content-fetch merged** (`feature/auto-content-fetch`,
  PR #9, into `dev`). Still open: whether to default it ON for do_catalog-like
  callers, and whether `max_len` needs tuning — content-dense inputs
  correlate with the worst per-item stalls regardless of model (see the
  dropped mimo-v2.5 finding above), so this is worth watching even with
  mimo-v2.5 gone.

## Eval harness

- **Full-100 do_catalog scale-up — delayed** (2026-08-11). Pilot (18 main +
  20 ORCID) x2 (v1/v2) complete and reported; full 100 pre-approved in scope
  but explicitly put on hold, not scheduled. Re-estimate cost/time before
  resuming, now that `--fetch` is in the mix (real per-item network latency).
