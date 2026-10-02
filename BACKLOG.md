# Backlog

Deferred, non-urgent improvements surfaced during development — not tracked
elsewhere (no issue tracker in use for this repo). Each item should carry
enough context to pick up cold; prune entries once actually done.

CDIF pivot decisions (field mapping, resolved questions) live in
`docs/codata_mcp_croissant_cdifspecs.md` Appendix A/B; only still-open items
are listed here.

## CDIF output / eval (open owner questions from the pivot)

- **O-1 — `schema:dateModified` semantics.** No agent produces it:
  `CDIFDiscoveryProfile._inject_envelope` stamps it with the processing date
  (`datetime.now(UTC).date()`). Should `core_metadata` extract the resource's
  real last-updated date when the source states one, falling back to today?
  Meanwhile `scripts/eval_common.py`'s `IGNORED_SCORING_FIELDS` keeps it out of
  live-eval scoring. Without that, every fixture fails the field by construction.
- **O-2 — Calibrate the live-eval gate.** `make live-eval` passes or fails on
  a GEval mean ≥ 0.75 (`config/eval.yaml`). GEval only emitted ~0.1-step values
  across the 6 golden fixtures (0.600/0.700/0.900), so 0.75 is a coarse
  line. The first real post-pivot run scored 0.767 (PASS, 2026-09-07), but no
  pre-B3 baseline exists, and the reference is circular: golden fixtures are
  the same model's own snapshots, unseeded on `opencode`. Decide whether to
  gate on the already-computed per-field judge mean instead (finer
  resolution), and recalibrate the threshold.
- **O-3 — Score `schema:audience`'s sub-fields?** Should `dcterms:mediator` /
  `schema:educationalLevel` / `dcterms:instructionalMethod` (stored as bare
  `mediator`/`education_level`/`instructional_method` keys inside
  `schema:audience`) be scored at all? They come from a large cross-product that
  no single golden answer covers representatively.

- **SHACL findings still produced by every golden fixture.** Top-level and
  nested `schema:identifier` / `schema:license` entries carry no `@type`
  (e.g. `["schema:PropertyValue"]`). The vendored shapes' `sh:class` checks
  (`resourceIdentifierProperty`, `rightsProperty`) therefore can't recognize
  them. Neither `identifier_enricher.py` nor the `config/agents.yaml` prompts add
  one, and a prompt edit means a cache invalidation plus a re-record. Some
  recordings also simply lack license/`conditionsOfAccess` content. Separately,
  `check_shacl_conformance` returns `sh:Info`/`sh:Warning`/`sh:Violation`
  results as plain strings with no severity, so decide whether to surface
  severity or filter to `sh:Violation` before ever defaulting
  `validate_shacl_conformance` on.

## Structure fetcher / DataDescription (deferred)

- **Structure fetcher (`enrichers/structure_fetcher.py`), not built.** Design is
  in the spec's §7; deferred per Appendix B Q10-Q12. When CDIF DataDescription
  work starts, it needs: a structure field on `ResourceDescription`;
  `agents/base.py::_build_resource_dict`'s fixed `dict[str, str]` key set
  extended to carry it; `PipelineConfig.enable_structure_fetch`; a
  `Pipeline._maybe_fetch_structure()` step mirroring `_maybe_fetch_content()`;
  and a "measured, never generated" invariant test on LLM *output* (generated
  columns ⊆ measured columns), not just the fetcher's input handling. Still open:
  Q10 (format list / bounded-sample strategy) and Q11 (ordering vs content-fetch).
- **Croissant `recordSet` / CDIF DataStructure (`cdifTabularData`), blocked on
  the above.** Both should be thin projections of one neutral measured
  structure record (spec §3.4). `exporters/croissant.py` omits `recordSet`
  today, which conforms because it is optional in Croissant 1.1. It is worth
  building once real column data exists, not because the omission is wrong.

## Identifier enrichment

- **Human ROR/ISNI curation step still not done.** The tooling exists:
  `scripts/curate_ror_isni.py` (candidate review file, CSV round-trip,
  `--promote-from`/`--promote-to`), plus `enrichers/identifier_overrides.py`
  wired via `PipelineConfig.identifier_overrides_path`. But no
  `config/overrides.yaml` has ever been created or committed, and the
  do_catalog ground truth's messy VIAF/Wikidata/malformed-ISNI identifiers have
  not been human-curated. Someone still has to review the candidates and
  promote the decisions.
- **Cross-border same-name institution collision — known accepted
  limitation, no fix planned.** The ROR `?query=` country hint
  (`fuzzy_matcher.match_organization`'s `country_hint`) is computed **once per
  resource** from the hosting page's URL/HTML (`CountryExtractor`). It is applied
  uniformly to every actor in `schema:creator` / `schema:contributor` /
  `schema:publisher` / `schema:funding`. Take a resource citing a foreign
  institution that shares a name with a domestic one (e.g. an Argentine vs
  Chilean "Instituto Nacional de Estadística"). The penalty can drop the
  correct foreign org below threshold, or let a same-named domestic decoy
  outrank it. It only flips outcomes when names are already near-identical.
  The ROR `?affiliation=` path has a parallel country cross-check (Appendix B
  O-5) that demotes, never drops. A real fix needs per-affiliation country
  detection from each affiliation's own address/context, which is a
  name-extraction task, not resolution. Mitigated, not solved, by the override
  store (once populated, see above) and by `matched_via`/`confidence`/`status`
  provenance on every attached identifier.
- **`CountryExtractor` runs redundantly, up to 6x per resource — not fixed.**
  `agents/base.py::_build_resource_dict` calls `extract_country()` once per
  agent (5 agents), and `pipeline.py`'s identifier-enrichment step calls it once
  more, with no memoization. Each call is a handful of bounded regex scans over
  `fetched_content` (capped by `content_fetcher.py`'s `max_len`), so the waste
  is sub-millisecond. Threading one precomputed value through `agents/base.py`,
  `orchestrator.py`, and `pipeline.py` isn't worth it unless `max_len` grows
  materially or profiling shows it matters.
- **Crossref Funder Registry path not pursued.** Funder identifiers inside
  `schema:funding[].schema:funder` are resolved via ROR (now issuing funder
  IDs) / ISNI only. Crossref's Funder Registry is a live alternative source
  that was never evaluated as its own enrichment path. Check what the DataCite
  exporter's `funder_identifiers` would gain before picking this up.
- **P2 — local ROR-dump ingestion, deferred, trigger-conditional.** Batch-load
  the Zenodo ROR dump instead of live API calls (as `openalex-guts` does). Do
  **not** implement by default. gema calls ROR a handful of times per resource
  behind a 30-day diskcache, and the real costs are a shipped artifact, a
  refresh job, and staleness. Size is not the blocker (measured 2026-08-25:
  137,398 orgs; Parquet minimal-fields zstd 6.8MB, all-fields 14.7MB).
  **Revisit only on** observed ROR rate-limiting in production batch runs, or a
  concrete offline/air-gapped requirement. "OpenAlex does this" is not enough.

## Content fetch

- **Content-density extraction for nav-chrome pages.**
  `content_fetcher.py::_extract_relevant_text` prefers `<main>`/`<article>` and
  skips `nav`/`header`/`footer`/`aside`/small `form` tags. It does not help on
  pages whose chrome sits in a generic layout `<div>` with no semantic
  container (e.g. do_catalog item `92`, `spensiones.cl`, a common Chilean
  gov-portal CMS template), or on pages like golden `sample_input03`
  (geoportal.cl), where the full nav block is duplicated into the text. In the
  2026-09-06 bake-off, only `trafilatura`'s boilerplate detection excised it.
  Real fix: a readability-style text-to-tag-density score per DOM subtree,
  or an evaluated trafilatura-style boilerplate pass behind a flag.
- **`max_len` tuning.** `clean_html_to_text`/`fetch_page_content` truncate
  at 8000 chars. This only matters if someone actually hits it in practice.
- **Re-bake golden `sample_input03`'s `fetched_content` from a real fetcher
  run.** `tests/fixtures/golden/inputs/sample_input03.json` carries
  28,002 chars of raw, unstripped HTML (Livewire page shell, inline styles, facts
  buried in `&quot;`-escaped `wire:snapshot` JSON). `_maybe_fetch_content` skips
  any input that already has `fetched_content`, so this reaches the
  `media_files` prompt verbatim. `clean_html_to_text` on the same content yields
  a clean ~3.1KB text with both distribution URLs and the variable terms.
  This is the likeliest cause of `schema:distribution`/`schema:variableMeasured`
  flipping between populated and empty across re-records, so it is a data
  problem, not a prompt one. Re-baking forces `make record-golden` plus a
  fresh `make live-eval` baseline. Check whether other golden inputs'
  pre-baked content (several exceed the fetcher's own truncation limit) should
  be re-baked in the same cycle, possibly with `enable_js_render_fallback` on
  for the JS-rendered `sample_input01`/`02`/`06`.

## Models / eval harness

- **Optional: diagnose `longcat-2.0` / `omen-alpha` latency.** In the
  2026-09-06 model-swap experiment both took 90-400+s per item, versus
  single-digit-to-~80s for `deepseek-v4-flash`. It was never distinguished
  whether that is model latency, opencode routing/queueing, or retries (`omen-alpha`
  hit retried 400s on `rights_funding_citations`). Only matters if either
  model is reconsidered (see Appendix B B2: staying on `deepseek-v4-flash`).

## Settled outcomes (kept so they aren't re-proposed)

- **Splitting `core_metadata` into two agents: evaluated, not recommended.**
  Prompt reorder plus per-agent decode order (`build_output_model`) moved
  nothing on the flagged weak fields, and their gaps traced to eval ground-truth
  noise, not architecture.
