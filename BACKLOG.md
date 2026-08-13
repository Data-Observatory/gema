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
  calling), not a prompt tweak. Same underlying gap the DOI-resolver
  enricher (above, done) and identifier enrichment work around post-hoc —
  neither helps the model get the name right in the first place, only
  resolves an identifier for whatever name it already produced. **Scoped,
  not implemented** (2026-08-11):
  - Real architecture change, not a prompt tweak: today every agent call is
    one stateless `LLMClient.complete()` producing a fully-formed
    `DataCiteOutputModel`. A tool the model can *choose* to call mid-
    reasoning needs a proper tool-call loop (send messages with `tools=`,
    execute any tool calls, append results, repeat until the model stops
    calling tools, then a final forced-structured-output call) — a new
    method on `InstructorLLMClient` (same optional/duck-typed pattern as
    `complete_with_usage`), a new optional `tools` param on `BaseAgent`,
    and a new YAML field so only `creators_publishers` opts in.
  - Recommended backend: reuse `RORClient` (already built, tested, and had
    a real bug fixed today) over a new web-search integration — ROR covers
    a huge range of orgs including many government ministries, it's free,
    live, and it's the *same* registry `IdentifierEnricher` already
    resolves against post-hoc, so a name confirmed during generation also
    resolves cleanly afterward. A static gazetteer (today's ~15-entry table,
    just callable) doesn't fix the actual coverage gap. Live web search
    needs a new dependency/API key/cost line for uncertain quality gain —
    revisit only if ROR coverage proves insufficient.
  - Scope narrowly to `creators_publishers` only; cap tool-call rounds
    (e.g. 2) so a stuck model can't loop indefinitely — each round is a
    full extra LLM request, roughly 2x latency/cost worst case.
  - Rollout: pilot via the same cheap deepseek-only do_catalog comparison
    used tonight, on `creators_publishers` alone, before deciding whether
    it's worth the added latency/cost — and before considering it for any
    other agent.
- **Split `core_metadata` into two agents** (identified during the 2026-08-11
  prompt review). It's twice the size of any other agent (9 reasoning
  steps, 9 output fields) and its weakest-quality fields (`geo_locations`,
  `temporal_events`, `alternate_identifiers`, `related_identifiers`) used
  to sit at the end, where a cheap model's instruction-following is
  weakest. **Minimum-effort fix done** (2026-08-11): reordered the existing
  prompt so those 4 fields are now PASO 2-4, right after resource
  identification, instead of PASO 6-8 at the end — no new agent, no
  wall-clock cost, golden fixtures re-recorded.

  **Re-measured against the do_catalog 18-pilot (deepseek-only, 2026-08-11)
  — full split NOT recommended on current evidence.** Aggregate structural
  score was flat (0.530 → 0.516/0.521, noise-level either way) but that
  metric can't isolate these 4 fields (`alternate_identifiers` is blended
  into a 15%-weight `field_coverage` blob and structurally unmeasurable on
  this corpus anyway — ground truth has it empty 0/18 times). Checked
  field-level output vs. truth directly instead:
  - `geo_locations`: 16/18 — fine.
  - `related_identifiers`: 7/18 (truth itself only has it 10/18) — moderate.
  - `alternate_identifiers`: model 1/18 vs. truth 0/18 — unmeasurable, truth
    never has any.
  - `temporal_events`: model 0/18 vs. truth 6/18 — the one real-looking gap.

  But spot-checking those 6 truth entries: several assign
  `frequency_type: "yearly"` to one-off resources (e.g. a single 2007
  census) with no explicit frequency statement in the description text the
  model was given. The prompt explicitly forbids inferring frequency from
  resource type (correct DataCite behavior) — so 0/18 may be the model
  correctly refusing to guess, not a prompt-position weakness. Same
  root-cause class as the "rights always 0.000" finding elsewhere in this
  corpus: ground truth may carry info the do_catalog input never exposes.
  **Before spending on the full split** (or on any further prompt work
  targeting these fields): pick 2-3 of those 6 `temporal_events` ground
  truth records (`tests/fixtures/do_catalog/ground_truth/`, look for
  non-empty `temporal_events`) and check the real source page/dataset to
  confirm whether the ground truth's frequency claim is actually correct
  and, if so, whether the *original* full record (not the reverse-extracted
  eval input) states it explicitly anywhere. If ground truth turns out to
  be noise (inferred from resource type, not a real declared frequency),
  this whole "weak field" framing may not need a code fix at all.
- **DOI-resolver enricher — done** (2026-08-11): `DOIResolverEnricher`
  (`enrichers/doi_resolver.py`) backfills titles/creators/publisher/an
  Issued date from Crossref's public Works API for DOI-identified
  resources, opt-in via `enable_doi_resolution` (default off). Scope is
  narrow by design (only what Crossref reliably returns; abstracts
  skipped) — runs before identifier enrichment so backfilled
  creators/publishers still get a shot at ROR/ISNI resolution.

## Identifier enrichment

- **Curated, human-reviewed ROR/ISNI ground truth** to replace the messy
  source data (do_catalog's raw VIAF/Wikidata/malformed-ISNI identifiers
  aren't reliable as strict ROR-only ground truth — the eval's scoring
  adapter works around this with scheme-aware matching, but the underlying
  source data quality issue is untouched). **Semi-automated helper built**
  (2026-08-11): `scripts/curate_ror_isni.py` queries ROR's API for
  candidate matches against every org name without an existing ROR
  identifier and writes a review file — nothing is auto-applied. The
  actual curation step (a human picks or rejects each candidate, then
  the ground truth files get updated) is still not done — this only
  removes the "look each one up by hand" grunt work.
  While building it, found and fixed a real, unrelated production bug:
  `RORClient.search_query` was sending an illegal `limit` param to ROR's
  live `?query=` endpoint, silently swallowed into "no results" for
  every query-endpoint fallback lookup since the client was written —
  see `fix(enrichers): stop sending an illegal limit param...`.

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
  execution either. **Done** (2026-08-11): `metagen list-known-providers`
  CLI command reads the same pool, for discoverability parity of the
  autofill convenience.
- **`max_workers` bump when production model moves off zai-coding-plan.**
  Currently pinned to 1 (`4101ac9`) because that provider's account rate
  limit is tight (429s even at `max_workers=2`). Confirmed empirically this
  session: `opencode:deepseek-v4-flash` handles `max_workers=5` with zero
  429s, ~3x wall-clock speedup per resource (18.7s vs ~57s summed). Safe to
  raise only if/when the default provider actually changes — don't touch it
  while still on glm-5.2. When it's time: use the existing 3-level cascade
  (`PipelineConfig.effective_max_workers(provider, model)` — global default
  with no concurrency assumed, provider-level override, provider-scoped
  model-level override), don't invent a new mechanism.
- **`mimo-v2.5` dropped from the eval model set** (decision, 2026-08-11): a
  content-dense DOI resource (`136`, GFZ dataset, 6000-char fetched_content)
  caused a 3244s (54min) stall for mimo-v2.5 vs. 1201s for glm-5-turbo on the
  same eval run — too unreliable to keep as a production candidate. Eval/prod
  model set going forward: `glm-5.2`, `glm-5-turbo`, `deepseek-v4-flash`.
- **Real production content-fetch merged** (`feature/auto-content-fetch`,
  PR #9, into `dev`), **left off by default** (decision, 2026-08-11):
  content-dense inputs correlate with the worst per-item stalls regardless
  of model (see the dropped mimo-v2.5 finding above) — flipping
  `enable_content_fetch` on for every caller of the default config without a
  scale eval to justify it isn't worth the risk. Stays an explicit opt-in.
  `max_len` tuning still open if/when someone actually opts in and hits it.

## Eval harness

- **Full-100 do_catalog scale-up — done** (2026-08-13). All 3 production
  models (`glm-5.2`, `glm-5-turbo`, `deepseek-v4-flash`), structural +
  LLM-judge (`opencode:qwen3.7-plus`), 100/100 succeeded each, 0 GEval
  failures. Structural numbers below are **corrected** (2026-08-13) for the
  `rights`-scorer empty-vs-empty bug fixed in `scripts/eval_common.py` (see
  the eval-scoring-bugs entry below) — rescored the same saved outputs at
  zero live-API cost via the new `--rescore-only` flag, delta is small
  (+0.001 to +0.003 per model, not the ~0.10 originally estimated before the
  fix was actually measured):
  | model | structural (corrected) | GEval | field-judge |
  |---|---|---|---|
  | glm-5.2 | 0.527 | 0.334 | 0.708 |
  | glm-5-turbo | 0.514 | 0.337 | 0.713 |
  | deepseek-v4-flash | 0.506 | 0.324 | 0.730 |

  All 3 land within a noise-level band on every metric — no clear quality
  winner. **deepseek-v4-flash recommended as default**: not worse on
  quality, real cost/speed win (opencode allows real concurrency,
  `max_workers:5`, vs. zai-coding-plan's rate-limit-forced
  `max_workers:1`). Reports at `reports/do_catalog/full100/` (gitignored,
  local only — not committed).

- **Eval-scoring bugs found and fixed in `scripts/eval_common.py`**
  (2026-08-13), following an Opus code review, a second adversarial Opus pass
  that recomputed several of the first review's claims against real data (and
  reversed two of them), and a third Opus pass that independently adjudicated
  those two disagreements by re-deriving the numbers itself rather than
  refereeing prose. Exact figures below are from that adjudication, verified
  again directly against the real 100 ground-truth files and all 300 saved
  full-100 outputs:

  - **`rights` scorer's empty-vs-empty case — fixed.** Was `0.0` when truth
    had no `rights_identifier`, unlike every other metric's `jaccard()`
    (`1.0` on empty-vs-empty). Only 1/100 ground-truth files are actually
    empty, so this was a small, mechanical fix (`overall` +0.001, see above),
    not the ~10%-of-weight bug an initial (wrong) reading suggested.
  - **`rights` — real, separate recall gap, NOT fixed here, needs a
    spot-check first.** Ground truth has `rights_identifier` populated on
    **99/100** files, almost all genuine SPDX ids (`CC-BY-4.0` ×66,
    `CC-BY-SA-4.0` ×18, `cc-by-4.0` ×4, `ODbL-1.0` ×3, plus singletons).
    Models emit *any* `rights` entry on only 8-13/100 items and **0/100**
    emit a non-empty `rights_identifier` — always the generic "Datos
    Abiertos del Estado de Chile" free-text fallback
    (`rights_funding_citations`'s PRIORIDAD 3 branch,
    `config/agents.yaml` ~880-884), never the specific SPDX id truth has.
    **Before touching the prompt**: spot-check 2-3 of the 66 `CC-BY-4.0`
    ground-truth files' real source pages to confirm the license was stated
    in text the do_catalog reverse-input extractor actually exposes (not
    sourced from an external catalog license field outside the given input)
    — same discipline as the `temporal_events` spot-check above. If
    confirmed extractable, this is a real `rights_funding_citations`
    prompt-priority bug (PRIORIDAD 3 firing ahead of an available, specific
    license mention); if not, it's the same "ground truth exposes more than
    the input" class as `subjects` below.
  - **`subjects` — ground truth is formal English LCSH subject headings**
    (`"Judicial statistics -- Chile"`, `"Household surveys - Chile"`), not
    phrases lifted from the Spanish source description; the prompt correctly
    forbids inventing terms not in the source text. Likely the same
    ground-truth-exposes-more-than-input class as `rights`/`temporal_events`
    — logged, not fixed; same spot-check treatment recommended before any
    prompt change.
  - **`media_formats` — the real, large gap, not `rights`.** Ground truth has
    a usable `format` on 94/100 items; pipeline output has a non-empty
    `media_files` on only **1-2 of 100** across every model
    (metric scores 0.055-0.065). The `media_files` agent is producing
    essentially nothing at scale. Its prompt is a deterministic rule table
    (extension→MIME, ArcGIS REST/WMS/WFS URL patterns) — the same kind of
    logic `enrichers/iana_normalizer.py` already implements. **Candidate
    fix**: convert `media_files` from an LLM agent to a post-merge
    deterministic enricher (fold URL discovery into `core_metadata`, which
    already harvests URLs for `related_identifiers`; move format/MIME
    inference to a new enricher reusing `iana_normalizer.py`). Not yet
    implemented — removes one of 5 agents (20% of per-resource LLM calls) if
    done.
  - **Accent folding added to `_norm()`** (NFKD, strip combining marks) as
    correctness hardening — confirmed to move **nothing** on this corpus
    (`creators_name`/`ror_match`-equivalent scores byte-identical before and
    after; zero ground-truth/output name pairs in this corpus differ only by
    accent). Kept for future corpora where that isn't true, not because it
    fixed anything here.
  - **`scripts/compare_models.py` gained `--rescore-only`**: re-scores
    already-saved outputs (`output_root/outputs/<label>/*.json`) instead of
    re-running the pipeline, falling back to a normal run when no saved
    output exists. Used to get every number above at zero live-API cost —
    worth reusing for any future scoring-function change.
