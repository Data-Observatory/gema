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

  **Decode-order fix landed (2026-08-13) and re-measured — does NOT explain
  the earlier flat result.** Root-cause finding: all 5 agents shared one
  `DataCiteOutputModel` (`schemas/datacite.py`), so Instructor's structured-
  output decode order was that model's one fixed field-declaration order for
  every agent, regardless of the prompt's own PASO order — meaning the
  2026-08-11 reorder above changed the *prompt text* but never actually
  changed *generation order*. Fixed via `Schema.build_output_model(fields)`
  (per-agent dynamic model, `reasoning` first then the agent's own fields in
  its declared order; see the per-agent structured-output model entry
  below for the cache-key implications). Re-ran the do_catalog 18-pilot
  (deepseek-only) with decode order now genuinely following the prompt:

  | | before (prompt reorder only) | after (decode order also fixed) |
  |---|---|---|
  | avg overall | 0.516 | 0.534 |
  | `geo_locations` | 16/18 | 18/18 (truth 18/18) |
  | `related_identifiers` | 7/18 (truth 10/18) | 7/18 (truth 10/18) — unchanged |
  | `alternate_identifiers` | model 1/18, truth 0/18 | model 1/18, truth 0/18 — unchanged |
  | `temporal_events` | model 0/18, truth 6/18 | model 0/18, truth 6/18 — unchanged |

  The aggregate +0.018 is real but modest, and `geo_locations` (already
  "fine" before, not one of the flagged weak fields) accounts for most of
  the field-level movement. **The two fields actually flagged as weak
  (`temporal_events`, `related_identifiers`) show zero change despite decode
  order now genuinely matching prompt order** — this is a real result, not
  a null one: it strengthens the earlier hypothesis that `temporal_events`'
  0/18 is the model correctly refusing to fabricate frequency data (per its
  own explicit rule), not a position/order artifact, since fixing position
  didn't move it at all. **Full agent split still NOT recommended** — the
  remaining evidence points at "genuinely hard field" or "ground truth
  noise" (see the `temporal_events` spot-check above, still open), not at
  architecture.

- **Per-agent structured-output model — done** (2026-08-13):
  `Schema.build_output_model(fields)` (new `Schema` Protocol method,
  implemented in `DataCiteSchema46`) builds a dynamic Pydantic model per
  agent via `pydantic.create_model` — `reasoning` first, then the agent's
  own `fields:` in their declared order — so an agent's prompt-level
  reasoning order actually controls Instructor/OpenAI structured-output
  decode order, instead of every agent decoding in the shared
  `DataCiteOutputModel`'s one fixed order (see the `core_metadata`-split
  entry above for why this mattered and what re-measuring it showed).
  `BaseAgent.run()` calls this instead of the bare `output_model` property;
  `output_model` itself is unchanged (still the schema-standard default
  order, used by `validate_output` and anything outside the per-agent
  path). **Cache-key detail, load-bearing**: `cache.py` keys the LLM
  response cache on `response_model.__name__` — the dynamic model's name is
  a stable hash of the field sequence, not a random/identity-based name, so
  the same agent shape reuses the same cache entries across process
  restarts, while a different field order or subset always gets a
  different name (so differently-shaped agents never collide on that
  cache). Shipping this invalidates the entire golden-fixture LLM-response
  cache — `make record-golden` (real API cost) was required, not a
  `make test-regression` replay. **Known gap, not fixed** (see "Code
  review findings, not yet fixed" below): the hash covers field
  names/order only, not each field's type definition.

- **Cross-agent context passing — done, piloted on
  `rights_funding_citations` only** (2026-08-13). Verified gap:
  `Orchestrator.run()` used to call `agent.run(resource)` with only the
  original input — `depends_on` controlled execution order only, no
  upstream agent's output ever reached a downstream agent's prompt.
  Concretely: `rights_funding_citations`'s `rights_holder` fallback rule
  ("if the text doesn't distinguish one, use the publisher") had no real
  publisher to use — only whatever it could independently re-derive from
  the same text `creators_publishers` already parsed separately in the
  same wave, no reconciliation between the two.

  Added: `AgentConfig.context_fields: list[str]` (which upstream field
  names an agent wants surfaced); `Orchestrator.run()` now accumulates
  every completed wave's *successful* fields into a running
  `dict[str, Any]` and passes it to every subsequent wave's
  `agent.run(resource, upstream_fields=...)` — accumulated across all
  prior waves, not just the immediately preceding one, since a dependency
  can sit more than one wave back. An errored upstream field is omitted
  entirely (never `None`) so a downstream agent can't confuse "upstream
  said empty" with "upstream failed." `rights_funding_citations` now
  declares `depends_on: [core_metadata, creators_publishers]` +
  `context_fields: [resource, publishers]`, and its `rights_holder` rule
  now explicitly points at the injected `publishers` block instead of
  re-deriving it from scratch. Golden fixtures re-recorded (only this
  agent's cache entries missed) and reviewed — no regressions,
  `rights_holder` correctly matches the injected publisher name where the
  source text didn't distinguish one (`sample_input05`).

  Re-ran the do_catalog 18-pilot (deepseek-only) — flat, as expected, and
  for a reason worth noting: 0.535 vs. Phase 3a's 0.534 baseline
  (noise-level). `scripts/eval_common.py`'s `rights` metric only scores
  `rights_identifier` (the SPDX id) — it never reads `rights_holder` at
  all, so this consistency fix is invisible to the current structural
  score by construction, not because it didn't work (the golden-fixture
  diff review confirms it did). If `rights_holder` consistency matters
  enough to measure, `eval_common.py` would need a metric for it — not
  scoped here.

  **Not yet wired**: `creators_publishers` itself (the other consumer that
  independently extracts overlapping stakeholder entities from
  `core_metadata`'s `resource.editor/maintainer/producer/contact`) —
  deferred pending review of whether this pilot's consistency win is worth
  the same treatment there, per the original scoping. **Also not
  cross-validated** (see "Code review findings, not yet fixed" below):
  `context_fields` entries aren't checked against the upstream agent's
  actual field names, so a typo silently injects nothing rather than
  erroring.

  **Known golden-fixture drift, flagged by an independent review, not
  fixed**: `sample_input06`'s `resource.contact` dropped to `""` across
  the two re-records this work required (Phase 3a's and this one), even
  though the source `fetched_content` explicitly labels it ("Contact
  Victor, Pia ; GFZ German Research Centre for Geosciences..."). Verified
  by reading the actual input text; `core_metadata`'s prompt was not
  touched by either re-record — this is ordinary live-LLM run-to-run
  nondeterminism on a field neither phase targeted, the same class of
  noise the 0.85 semantic-diff regression threshold exists to tolerate —
  not re-recording again just to chase one field on a non-production demo
  fixture.

- **DOI-resolver enricher — done** (2026-08-11): `DOIResolverEnricher`
  (`enrichers/doi_resolver.py`) backfills titles/creators/publisher/an
  Issued date from Crossref's public Works API for DOI-identified
  resources, opt-in via `enable_doi_resolution` (default off). Scope is
  narrow by design (only what Crossref reliably returns; abstracts
  skipped) — runs before identifier enrichment so backfilled
  creators/publishers still get a shot at ROR/ISNI resolution.

  **Bugs found in this enricher and fixed** (2026-08-13), via an Opus code
  review of the not-yet-merged PR carrying it:
  - Was silently dropping Crossref institutional authors (`{"name": ...}`,
    no `family`/`given`) entirely — exactly the government/agency DOI-authorship
    case this project targets. Now becomes an `Organizational` creator.
  - Name format was Crossref's raw `"Given Family"`; now
    `"Family, Given"`, matching `creators_publishers`' own
    `"Apellido, Nombre"` convention so DOI-backfilled and LLM-produced
    `creator_name` values are directly comparable (`creators_name` is 20%
    of eval weight, scored by exact string match).
  - Backfilled creators/publishers were missing keys
    (`email`/`genre`/`type`/`contributor_type` on creators, `lang` on
    publishers) that every LLM-produced record always carries, since this
    enricher runs post-merge and bypasses
    `_normalize_creators`/`_normalize_publishers`. Now emits the full key set.
  - `_backfill_issued_date` was all-or-nothing: skipped adding the
    authoritative Crossref `Issued` date if *any* date already existed
    (e.g. an agent-produced `Collected` date). Now only skips if an
    `Issued`-typed entry already exists. Also now backfills
    `resource.publication_year` from the same Crossref data (previously
    never touched despite the year being available right there).
  - `CrossrefClient.get_work`: the DOI was interpolated into the URL path
    unquoted — a DOI containing `?`/`#` would silently truncate the path
    before the request reached Crossref. Now URL-encoded
    (`quote(doi, safe="/")`, preserving the DOI's own literal `/`). Also now
    strips a leading `doi:` prefix (only the `https://doi.org/` form was
    stripped before).
  - `scripts/curate_ror_isni.py` was skipping the affiliation-collection loop
    for Personal-creator roles entirely, dropping exactly the
    university/agency names most needing ROR curation (do_catalog's rare
    Personal creators are the ones most likely to carry an affiliation at
    all). Fixed to collect affiliations regardless of the role's own
    name_type.
  - `metagen list-known-providers`'s `providers.yaml` lookup was a bare
    cwd-relative `Path("config/providers.yaml")`, unlike every other
    config-reading command (which goes through `find_config()`'s
    multi-location search cascade). Now resolved as a sibling of wherever
    `agents.yaml` itself was found (same `--config`/`-c` override as
    `list-providers`), so it works from any cwd.

- **Golden-fixture regression found and fixed before merge** (2026-08-13,
  on `chore/backlog-batch-2-8`, before PR #16 reached `dev`): a prior golden
  re-record (`b1ed4d4`) had baked in `creators_publishers` truncating full
  given names to initials (`"Sarricolea, Pablo"` → `"Sarricolea, P."`) —
  flagged by an Opus review as contradicting that agent's own worked example.
  **Correction made carefully, not blindly**: checked the actual source text
  for that fixture (`tests/fixtures/golden/inputs/sample_input03.json`) before
  writing a fix, and found the source itself only ever writes the author as
  `"Sarricolea P."` (a bibliographic citation, initial-only) — it never states
  the full name "Pablo" anywhere. The *first* prompt fix attempted here
  ("always use the full given name, never an initial") was itself wrong: it
  would have pushed the model to invent a full name from parametric memory
  whenever the source only gives an initial, which directly contradicts this
  project's own repeated "never invent beyond the given text" principle
  (the same rule already applied to `rights`/`subjects`/`temporal_events`
  elsewhere in this file). Corrected to a format-*preserving* rule instead —
  transcribe the given name exactly as the source presents it, whether that's
  a full name or an initial, never truncate a full name given in the source
  and never expand an initial the source gives — then re-recorded goldens and
  reviewed the full diff again before committing (the step that was skipped
  the first time). No other regressions found in that second review; the
  remaining diffs across all 6 golden fixtures are ordinary live-LLM
  paraphrase/reordering variance in fields untouched by this fix.

  Also folded into this same re-record (all touch `config/agents.yaml`):
  - `classification`'s PASO 4 dropped "Varía la combinación... no repitas
    siempre el mismo par" — an anti-determinism instruction at
    `temperature: 0.0` that could only hurt a set-match metric, visible as
    unexplained `audiences` churn in golden diffs.
  - Removed `use_chain_of_thought: false` from all 5 agents — confirmed dead
    (stored on `AgentConfig` but read by no pipeline/agent/orchestrator code;
    only referenced in `config/migrate.py`'s legacy-JSON direct-copy field
    list, which is unaffected since it reads the *source* JSON, not this
    YAML).

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
- **`LLMConfig.timeout` (60s default, `llm/base.py:73`) is too tight for the
  biggest agent + large payload combo, not fixed.** `core_metadata` (9
  output fields, the largest prompt) against `sample_input03.json` (~28KB
  `fetched_content`, next-largest input is ~7KB) reproducibly timed out at
  60s on `zai-coding-plan`/glm-5.2, retried for ~22min (tenacity backoff),
  then hard-failed — identically, 3 out of 3 separate `record_golden.py`
  runs on 2026-08-14 (plus once earlier during a different branch's
  recording). Confirmed not random flakiness: raising the timeout to 240s
  (temporarily, reverted before commit) let it succeed first try. No
  per-provider override exists today (`ProviderConfig` has no `timeout`
  field). Fix candidates: bump the global default past 60s, or add a
  per-provider/per-agent `timeout` override in `config/providers.yaml` /
  `config/agents.yaml` for large-payload agents specifically.

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
  - **`media_formats` — large gap on the full-100 corpus specifically, NOT
    an agent/prompt bug — verified root cause (2026-08-13, corrected
    2026-08-14 after an independent review caught two wrong facts in the
    first version of this entry).** Ground truth has a usable `format` on
    94/100 items; the full-100 pipeline run (`data/do_catalog/inputs/*.json`,
    the actual corpus this statistic comes from) has a non-empty
    `media_files` on only **1-2 of 100** across every model (metric scores
    0.055-0.065) — initially read as "the `media_files` agent is producing
    essentially nothing at scale" and its prompt "just a deterministic rule
    table", with a candidate fix to convert it to a post-merge deterministic
    enricher.

    **Checked before implementing that fix, and the fix's premise doesn't
    hold up — though two of the original supporting claims here were
    themselves wrong and are corrected below:**
    - **Corrected claim**: `scripts/reverse_input.py`'s `ALLOWED_KEYS` is
      `{url, title, description, publisher, fetched_content}` —
      `fetched_content` **is** allowed, has been since this toolchain's own
      introduction; the original entry wrongly said it was excluded by
      design. `scripts/generate_inputs.py --fetch` is what actually
      populates it, and it's opt-in (default off) for cost/reliability
      reasons, not a "test pure extraction" design choice.
    - **Corrected claim**: the 18-item pilot corpus
      (`tests/fixtures/do_catalog/inputs/`) is **not** input-starved —
      14/18 of its files carry real `fetched_content` (1.7-28KB), and 5/18
      (`205`, `360`, `366`, `376`, `377`) contain literal downloadable file
      URLs (`.zip`/`.kmz`). The original entry's "confirmed 0/18" claim was
      wrong — it came from a regex check that only searched `description`
      and `url`, not `fetched_content`, and so missed the very field where
      a download link would actually appear.
    - **What actually holds, re-verified directly against the right
      data**: the **full-100 corpus specifically** (`data/do_catalog/inputs/`,
      the one that produced the 94-vs-1 statistic) has **0/100** files with
      `fetched_content` and **0/100** with a discoverable file URL — that
      batch was generated without `--fetch`. And on the 18-pilot's 5 items
      that *do* carry a real file URL in `fetched_content`, the agent
      produces a **perfect match**: 5/5 correct `media_files` counts, with
      the exact real `file_uri` values, cross-checked against ground truth
      (`reports/do_catalog/pilot_phase3c/outputs/opencode__deepseek-v4-flash/{205,360,366,376,377}.json`).
      This is stronger, more directly relevant evidence than the original
      entry's golden-fixture cross-check (which used an unrelated 6-item
      fixture set, not do_catalog data at all) for the same conclusion:
      **the agent works correctly when given real content; the full-100
      gap is that specific batch missing `fetched_content` entirely, not
      an agent defect.** A deterministic enricher would find exactly as
      little on that same batch's inputs.

    **Not implementing the deterministic-enricher rewrite — the premise
    doesn't hold, still open.** Concrete, cheap next step if `media_formats`
    quality on the full-100 corpus matters: regenerate it with
    `generate_inputs.py --fetch` (already exists, opt-in) and re-run the
    structural comparison — given the 5/5 pilot result, this is a
    reasonable bet, not just a hopeful guess. Separately, whether to default
    `enable_content_fetch` on for production traffic generally is still the
    open, unrelated latency-stall question already logged above.
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

## Code review findings, not yet fixed

Three low-severity items from the final Opus review of the Phase
3a/3b/3c stack (2026-08-14), judged non-blocking for merge at the time —
recorded here since they weren't written down anywhere else and got lost
once that session ended.

- **`extract_rights_id` (`scripts/eval_common.py:251-255`) only reads
  `rights[0]`**, ignoring the rest of the array. A record with a second,
  correct `rights_identifier` entry after a non-matching first one would
  score as a miss. Still present as of 2026-08-14.
- **`Schema.build_output_model`'s cache-name hash (`schemas/datacite.py`)
  covers field names/order only, not each field's type definition.** If a
  field's type in `DataCiteOutputModel` changes later without renaming it,
  a stale cached response for the old type could theoretically slip
  through `cache.py`'s `response_model.__name__`-keyed lookup. Theoretical,
  not hit in practice — the dynamic model's name is a hash of
  `tuple(fields)` (`schemas/datacite.py:build_output_model`), confirmed
  unchanged as of 2026-08-14.
- **`AgentConfig.context_fields` isn't cross-validated against the
  referenced upstream agent's actual output fields**
  (`config/models.py:PipelineConfig._validate_references` only checks
  `depends_on` IDs, not `context_fields` names). A typo'd field name
  silently injects nothing at runtime rather than raising at config-load
  time. Still present as of 2026-08-14.
