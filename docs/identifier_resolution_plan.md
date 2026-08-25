# Identifier Resolution Improvement Plan (ROR / ORCID / ISNI)

**Created:** 2026-08-25
**Status:** P0 and P1 fully done (2026-08-25). P2 intentionally not started — stays trigger-conditional, not default work (see its own section). All recommended work in this plan is now complete; P2 is the only remaining item and it's a deliberate non-default.
**Trigger:** Comparison of `gema`'s identifier-enrichment subsystem against `openalex-guts` (OpenAlex's backend pipeline), reviewed independently by Opus after an initial pass.

## Goal

`gema` resolves organization/person names to ROR, ISNI, and ORCID identifiers post-LLM-merge (`enrichers/identifier_enricher.py`, `enrichers/identifier_resolver.py`). Comparing this subsystem against `openalex-guts`'s institution-matching machinery surfaced concrete, low-risk improvements — plus confirmed several things `gema` already does better. This plan scopes only the improvements worth making; it explicitly rejects approaches that fit OpenAlex's corpus-graph scale but not `gema`'s single-resource, single-maintainer, uv/pydantic-driven design.

**Scope:** identifier *resolution* quality for the existing ROR/ISNI/ORCID pipeline. Out of scope: DataCite schema coverage gaps (`contributors`, `funderIdentifiers` — see §6), and anything requiring a corpus-wide graph.

---

## P0 — do now

### 1. Wire `detected_country` into ROR/ISNI matching — DONE (2026-08-25)

Implemented on `feature/identifier-resolution-improvements`. `ror_client.extract_country` (ROR v2 `locations[0].geonames_details.country_code`), `fuzzy_matcher.match_organization`'s `country_hint`/`country_key`/`country_penalty` params (soft re-rank of the *entire* candidate set, not just the old top-2 fast path, when a hint is given — unchanged fast path when it isn't), `identifier_resolver.resolve()`'s `country` param (reaches `_try_ror_query` only, never `_try_isni`), `_make_key`'s country-folded cache key, `identifier_enricher.enrich()`'s `country` param threaded through creators/affiliations/publishers/funders, and `pipeline.py`'s `_process_resource` computing `detected_country` from the resource (same `CountryExtractor` call `agents/base.py` already uses) and passing it to `self._enricher.enrich()`. New tests: `TestExtractCountry` (`test_ror_client.py`), `TestMatchOrganizationCountryHint` (`test_fuzzy_matcher.py`), `TestCountryHint` (`test_identifier_resolver.py`), `TestCountryPassthrough` (`test_identifier_enricher.py`), plus 2 pipeline-level tests. Full suite green (897 passed), ruff clean, mypy clean on all touched files (pre-existing unrelated `yaml`/`instructor` stub errors elsewhere, not introduced by this change).

`enrichers/country_extractor.py` already derives a country signal (ccTLD, `og:locale`, `geo.country`, `html lang`) and `agents/base.py:75` already injects `detected_country` into every agent prompt — but nothing in `ror_client.py`, `identifier_resolver.py`, or `fuzzy_matcher.py` ever reads it. This is the single highest-value, lowest-cost fix identified: it's plumbing an existing signal into a matcher that currently ignores it, not new capability.

| File | Change |
|------|--------|
| `enrichers/ror_client.py` | **New helper needed** — `extract_country(org) -> str \| None`. ROR **v2** (this client is pinned to `/v2/organizations`) stores country at `locations[0].geonames_details.country_code`, not the v1-era `country.country_code`. No such extractor exists today; add it alongside `extract_isni`/`extract_parent`. |
| `enrichers/identifier_resolver.py` | Thread country through `resolve()`/`resolve_person()` so it reaches `_try_ror_query` (via `fuzzy_matcher`). **Do not thread into `_try_isni`** — `parse_isni_response` (`isni_client.py`) only ever yields `isni`/`isni_uri`/`name`/`org_type`; ISNI SRU results carry no country field to filter on. |
| `enrichers/fuzzy_matcher.py` | `match_organization` gains an optional country filter/boost — candidates whose ROR country (from the new `extract_country`) disagrees with the hint are deprioritized, not eliminated |
| `enrichers/identifier_enricher.py` | `enrich()` gains a `country: str \| None` parameter, passed down to `resolve()`/`resolve_person()` calls |
| `pipeline.py` | Country **cannot** come from `document.get_field("resource")` — `_normalize_resource` (`schemas/datacite.py`) builds a fixed dict that carries neither `url` nor a country field. It must come from the original `ResourceDescription` at the point `_process_resource` calls `self._enricher.enrich(document)` (`pipeline.py:138` area) — pass it through as the new `country` arg above. |
| `enrichers/identifier_resolver.py` | **Cache key must change too.** `_make_key` currently hashes only `kind:normalized_name` (30-day TTL). Once country affects matching, the same org name in two countries would collide on one cached result — fold country into the key. This is the same load-bearing-cache-key class CLAUDE.md already flags for `cache.py:_make_key`; existing `~/.cache/gema/identifiers` entries go cold on deploy, which is expected, not a bug (see Critical Risks). |

**Tests to update:** `tests/test_fuzzy_matcher.py`, `tests/test_ror_client.py`, `tests/test_identifier_resolver.py`, `tests/test_identifier_enricher.py`.

**Hard constraint:** treat this as a *hint, not a gate*. An empty or generic-TLD (`.org`, `.com`) detection must never reject an otherwise-good match — many Data Observatory sources are internationally hosted. Country disagreement should lower confidence / break ties, not hard-fail.

### 2. Persistent curation override store — DONE (2026-08-25)

Implemented on `feature/identifier-resolution-improvements`. New `enrichers/identifier_overrides.py:IdentifierOverrides` loads `config/overrides.yaml` (a list of `{name, country?, ror_id?, isni_id?}` entries — plain list, not the pipe-joined-string-keyed dict this section originally sketched, for human-editability), keyed internally on `(normalized_name, country)` with a country-specific entry preferred over a country-less fallback. `IdentifierResolver.resolve()` checks it first — before the disk cache, before any network call, not itself cached (already free). New `PipelineConfig.identifier_overrides_path: str | None` field, wired into `pipeline.py`'s existing `enable_identifier_enrichment` construction branch. `scripts/curate_ror_isni.py` gained a `--promote-from`/`--promote-to` mode: its review-file entries now start with `approved_ror_id`/`approved_isni_id`/`country` as human-fillable `null` placeholders, and promotion only ever picks up entries where a human has actually filled one in — merges into `overrides.yaml` by `(name, country)`, so re-promoting after further review updates rather than duplicates. Closes the BACKLOG.md "Identifier enrichment" section's open curation-step item (see §7 below). New tests: `tests/test_identifier_overrides.py` (16), override-precedence tests in `test_identifier_resolver.py` (6), 2 pipeline-wiring tests. Fails soft throughout — a missing/empty/malformed overrides file never raises. Full suite green (920 passed), ruff clean; mypy clean modulo the same pre-existing `yaml`/`instructor` stub-resolution gap already present on 4 other files before this work (`types-PyYAML` is a declared dependency but mypy doesn't find its stubs in this dev environment — not something introduced by this change, not chased further here).

Original scoping, for reference: `scripts/curate_ror_isni.py` (built 2026-08-11, see BACKLOG.md §"Identifier enrichment") generates a one-off review file of ROR API candidates for org names lacking an identifier — nothing is auto-applied, and the actual human curation step was never finished. This plan turns that dead-end review file into a live, durable input to resolution instead of a throwaway artifact.

| File | Change |
|------|--------|
| `config/overrides.yaml` (new) | `{normalized_name}|{country}: {ror_id, isni_id, ...}` entries, human-curated |
| `enrichers/identifier_resolver.py` | `resolve()`/`resolve_person()` check the override store *before* the disk cache and before any network call |
| `scripts/curate_ror_isni.py` | Extend so its review-file output can be promoted directly into `config/overrides.yaml` format after human review, instead of being a dead-end artifact |
| `config/models.py` (`PipelineConfig`) | New field (e.g. `identifier_overrides_path: Path \| None`) — `pipeline.py:138` currently constructs a bare `IdentifierResolver()` with no way to reach an overrides file; needs a constructor param and pipeline wiring |

Key on `(normalized_name, country)`, not name alone — "Ministerio de Salud" resolves to a different ROR per country, and collapsing the key to name alone would silently misattribute one country's ministry to another.

**Tests to update:** `tests/test_identifier_resolver.py` (new override-precedence tests), `tests/test_pipeline.py`/config tests for the new field.

### 3. Exploit ROR's own `external_ids` — with a corrected rationale — DONE (2026-08-25)

Implemented on `feature/identifier-resolution-improvements`. `IdentifierResolver._try_resolve` now returns a ROR match as-is (no independent ISNI SRU call at all) whenever it already carries its own linked `isni_id` — the class docstring and `_merge_org_matches`' docstring were rewritten to match (the "always checks BOTH registries... either can independently confirm" claim was false the moment `_merge_org_matches`'s `min()`/`"review" if either side is` logic is read closely: the independent check could only ever demote, never confirm). Confirmed real, not free: `matched_via` for a ROR-affiliation match with its own ISNI changed from `"ror_affiliation+isni_sru"` to plain `"ror_affiliation"`, and any case where ISNI-SRU previously demoted such a match to `"review"` now comes back `"auto"`. `TestMergeBothSources`'s two affected tests rewritten (`test_isni_skipped_when_ror_already_has_its_own_isni`, `test_rors_own_linked_isni_returned_as_is`), one new test added for the `?query=`+fuzzy path; the merge/demotion tests on the still-reachable path (ROR record genuinely carrying no ISNI) needed no change. Full suite green (921 passed), ruff clean, mypy clean on the touched file (same pre-existing `yaml`-stub gap noted in P0#2, unrelated).

Every ROR v2 record `gema` already fetches carries an `external_ids` array that can include ISNI, GRID, Wikidata, and FundRef IDs (`ror_client.py:extract_isni` already reads the ISNI case). Currently `identifier_resolver._try_resolve` still runs an **independent** ISNI SRU search and merges it with whatever ROR returned via `_merge_org_matches`.

**Correction to the original rationale:** `_merge_org_matches` (`identifier_resolver.py`) computes `confidence = min(ror_match.confidence, isni_match.confidence)` and `status = "review" if "review" in (ror_match.status, isni_match.status) else "auto"`. The independent ISNI check can therefore only ever **demote** a ROR hit's confidence/status — it is not a confirmation signal that raises trust, contrary to how the original comparison framed it ("either can independently confirm"). Skipping the independent ISNI check when ROR already found a linked ISNI is still worth doing (removes network calls, removes disagreement noise between two independently-fuzzy-matched IDs for the same org) — but it is a **real behavior change, not a free no-op**: some matches that today get demoted to `"review"` by ISNI-SRU disagreement will become `"auto"` once ISNI-SRU is skipped. This must be reviewed on a real sample before landing, not assumed neutral.

| File | Change |
|------|--------|
| `enrichers/identifier_resolver.py` | `_try_resolve`: only fall back to `_try_isni` when ROR found no match, or when ROR's match carried no linked ISNI. Also update the class docstring (lines ~33-45, "always checks BOTH registries... either can independently confirm") — that claim becomes false. |
| `enrichers/ror_client.py` | No change needed — `extract_isni` already reads `external_ids`; consider adding `extract_external_id(org, id_type)` generalized helper if GRID/Wikidata become useful later (not required for this item) |

**Tests to update:** `tests/test_identifier_resolver.py::TestMergeBothSources` (7 tests, including `test_isni_always_checked_even_when_ror_affiliation_succeeds`, which asserts `matched_via == "ror_affiliation+isni_sru"` — this assertion is exactly what this change removes and needs rewriting, not just re-running).

### 4. Persist match provenance — DONE (2026-08-25)

Implemented on `feature/identifier-resolution-improvements`. Two new helpers in `identifier_enricher.py` — `_identifier_entry` (list-entry shape: `name_identifiers`/`funder_identifiers`, provenance as unprefixed sibling keys `matched_via`/`confidence`/`status`) and `_provenance` (single-slot shape: `affiliation_identifier`/`publisher_identifier`, provenance as `{field}_matched_via`/`{field}_confidence`/`{field}_status` — prefixed to avoid colliding with any other key on that dict). Applies uniformly to every source: ROR/ISNI org matches, ORCID person matches, and overrides (transparently, since an override just returns an `IdentifierMatch` with `matched_via="override"` through the exact same code path — no special-casing needed). Confirmed the "no stripping risk" prediction correct by running the real pipeline: the golden-fixture re-record below shows the new keys landing in the output untouched. 8 new tests (`TestProvenance`, `test_identifier_enricher.py`) covering all four field shapes, ORCID, override passthrough, and `review`-status preservation.

**Required a golden-fixture re-record** (`make record-golden`, real LLM + live ROR/ISNI/ORCID calls, user-approved given the API cost/fixture-touching implications) — the new keys are a real output-shape change, exactly the case `CLAUDE.md` flags. Diff reviewed field-by-field before committing: identifier-related changes are exactly the new provenance keys; everything else (wording, creator-name variants, category counts) is ordinary live-LLM/live-registry nondeterminism unrelated to any P0 change — confirmed no agent prompt, schema normalizer, or org-name-extraction code was touched anywhere in P0#1-4. All 6 fixtures pass again (previously 5/6 failed at `creators`/`publishers` similarity 0.000 immediately after this change, before re-recording). Full suite green (928 passed), ruff clean, mypy clean on the touched file.

Original scoping, for reference: `IdentifierMatch` carries `confidence`, `matched_via`, and `status` internally (`identifier_types.py`), but none of it survives into the written `MetadataDocument` — a curated catalog has no record of *why* an identifier was attached, which matters more here than for OpenAlex (which only tracks a bare numeric confidence).

**Correction:** there is no stripping risk to guard against here, so this is simpler than it first looked. `IdentifierEnricher` runs post-merge (`pipeline.py`, after the schema normalizers have already built the document) and is never re-run through `_normalize_creators`/`_normalize_funding_references` afterward — so nothing downstream can strip anything the enricher adds. Separately, even if a normalizer *did* re-run, `name_identifiers`/`funder_identifiers` are passed through **wholesale** (`item.get("name_identifiers", [])`, `schemas/datacite.py:434,452,819`) rather than rebuilt key-by-key from an allowlist, so nested sibling keys inside each identifier dict would survive regardless.

| File | Change |
|------|--------|
| `enrichers/identifier_enricher.py` | When writing `name_identifiers`/`affiliation_identifier`/`funder_identifiers`, also record `matched_via`, `confidence`, `status` alongside the identifier — sibling keys inside each identifier dict is fine given the passthrough behavior above |
| `schemas/datacite.py` | No change needed — confirmed passthrough. Only verify `exporters/`'s output writer doesn't independently re-filter identifier dict keys before serialization. |

**Tests to update:** `tests/test_identifier_enricher.py`.

---

## P1 — locale-aware normalization — DONE (2026-08-25)

Implemented on `feature/identifier-resolution-improvements`. `fuzzy_matcher.normalize_org_name` gained accent folding (NFKD, drop combining marks — mirrors `scripts/eval_common.py`'s existing `_norm()` rather than adding a `unidecode` dependency) and a Spanish institutional-abbreviation dict, applied before legal-suffix stripping and punctuation removal.

**Deviation from the original scoping, found during implementation:** the abbreviation dict does NOT include a bare `u.` → `universidad` entry as first drafted — only the compound `u. de` → `universidad de`. A bare `u.` collided with the very common `U.S.`/`U.K.`/`U.N.` initial-letter pattern; caught as a real false positive on `"U.S.-Chile"` by the existing `test_preserves_hyphens` test before it ever shipped. Also, per the original scoping's own reasoning, did **not** add a hardcoded acronym→full-name dictionary (`UdeC`/`PUC`-style — this needs verified institutional ground truth, belongs in the P0#2 overrides store instead) or Portuguese-specific abbreviation forms (no real Portuguese-corpus data to verify against; accent folding alone already normalizes most Spanish/Portuguese spelling differences for free). `WRatio@90` kept unchanged as scoped.

**Required a second golden-fixture re-record** in the same session (same `make record-golden` procedure, same review discipline as P0#4's) — normalization changes shift which ROR/ISNI candidate wins a fuzzy match. Diff reviewed field-by-field: the identifier-matching shifts are legitimate (e.g. a shorter re-extracted creator name correctly resolving with lower confidence via ISNI instead of a stale high-confidence ROR match keyed to a longer name string it no longer received). Also surfaced and fixed a third fixture-dependent test outside the regression suite itself — `tests/test_dataverse_export.py::TestAgainstRealGoldenFixture` hardcoded a literal creator name and ROR scheme read from the same golden file. 12 new tests (`TestAbbreviationExpansion`, `test_fuzzy_matcher.py`) plus 2 rewritten (the old accent-preservation test now asserts folding). Full suite green (939 passed), ruff clean.

Original scoping, for reference: `fuzzy_matcher.py`'s `_LEGAL_SUFFIXES` regex only strips Anglo/EU commercial suffixes (`inc|ltd|llc|gmbh|corp|...`) and `normalize_org_name` has no abbreviation-expansion step at all. `openalex-guts`'s `RORStrategy` does both (unidecode folding + a hand-written abbreviation dict), but its dict (`univ→university`, `inst→institute`, `tech→technology`) is English-centric and near-useless for the Chilean/LatAm public-sector corpus `gema` actually processes.

| File | Change |
|------|--------|
| `enrichers/fuzzy_matcher.py` | Add a Spanish/Portuguese abbreviation-expansion step ahead of/alongside `_LEGAL_SUFFIXES`: `u. de → universidad de`, `univ. → universidad`, `min. → ministerio`, `inst. → instituto`, common acronym forms (`UdeC`, `PUC`-style), Portuguese equivalents |
| `enrichers/fuzzy_matcher.py` | Add unidecode-style accent folding to `normalize_org_name` (steal this part of `openalex-guts`'s normalization verbatim — it's locale-agnostic) |

**Explicitly do not change:** keep rapidfuzz `WRatio` at threshold 90. `openalex-guts` uses `partial_ratio_alignment` at 96 because it's extracting an org name out of a long, messy raw affiliation string — that scorer inflates scores for names that are substrings of longer candidates, which is a real risk against `gema`'s clean, LLM-emitted names (e.g. "Instituto de Física" would score artificially high against "Instituto de Física de la Universidad de Chile"). `WRatio` is the right tool for gema's input shape.

**Tests to update:** `tests/test_fuzzy_matcher.py`.

---

## P2 — deferred, trigger-conditional

### Local ROR-dump ingestion

`openalex-guts` avoids live ROR API calls entirely by batch-loading the full Zenodo ROR dump into an Elasticsearch index on a periodic job (`scripts/update_ror_institutions.py`, ~8h cadence). This is real engineering, but it exists to solve a problem `gema` doesn't have: `openalex-guts` matches hundreds of millions of works against ROR; `gema` calls ROR a handful of times per resource, behind a 30-day diskcache.

**Do not implement by default.** The costs are real for a single-maintainer project: shipping a ~100k-record artifact, building and maintaining a refresh job, and accepting data staleness between refreshes.

**Trigger condition to revisit:** actual observed ROR API rate-limiting in production batch runs, or a concrete requirement for offline/air-gapped operation. "OpenAlex does this" is not sufficient justification on its own.

---

## Explicitly out of scope / rejected

- **Forking or vendoring `openalex-guts`.** It is an operations codebase for one team's Django/Postgres/Elasticsearch/Redshift-SQL stack — no package, no release cadence, no stable API contract, and its `RORStrategy` depends on an ES index only their own batch pipeline builds. The strategic recommendation (see conversation record) is to cherry-pick ideas and write gema-native implementations (~200 lines total across the items above), not to fork or vendor. This holds unconditionally at `gema`'s current scope; it would only be revisited if `gema` needed corpus-level identity resolution across a whole catalog — and even then, the right move is consuming OpenAlex as a data source (public API/snapshot), not running their pipeline.
- **Cross-corpus author disambiguation ("AND"-style clustering).** `openalex-guts` doesn't even implement this itself — it's a separate external system upstream of the repo we inspected. `gema` has no corpus-wide graph (single-resource enrichment by design), so there's nothing to cluster against.
- **OpenAlex's specific abbreviation dict and `partial_ratio_alignment@96` scorer.** Wrong locale and wrong input-shape fit, respectively — see P1.

---

## Also flagged, out of scope for this plan

Two real metadata-completeness gaps surfaced during the Opus review, bigger wins than incremental identifier-matching precision, but they're schema-coverage gaps, not identifier-*resolution* gaps, so they don't belong in this plan:

- DataCite's `contributors` field (distinct from `creators` — `ContactPerson`, `DataCurator`, etc.) is entirely unmodeled in `schemas/datacite.py`.
- `funding_references[].funder_identifiers` — ROR now issues identifiers for funders too, and Crossref's Funder Registry is a live source — not currently pursued as a distinct enrichment path from org identifiers.

---

## BACKLOG.md cross-reference

This plan extends and is intended to close the open item in BACKLOG.md's **"Identifier enrichment"** section: `scripts/curate_ror_isni.py` was built 2026-08-11 to generate ROR-candidate review files, but "the actual curation step (a human picks or rejects each candidate...) is still not done." P0 item 2 above (`config/overrides.yaml`) gives that human-curation step a permanent destination instead of a one-off file — once implemented, that BACKLOG.md entry should be marked done/closed rather than left open indefinitely.

**Recommendation, not yet actioned:** add a new BACKLOG.md entry once implementation of this plan actually starts, following the file's existing "deferred, non-urgent, enough context to pick up cold" convention. Not added by this document — left for whoever picks up the work.

---

## Critical Risks

1. **Country signal is a hint, not ground truth.** `detected_country` can be empty or wrong (generic `.org`/`.com` TLD, no `og:locale`/`geo.country`/`html lang` present). Filtering on it as anything harder than a tie-break/confidence-adjust risks rejecting correct matches for internationally-hosted Data Observatory sources — this is the P0#1 hard constraint, called out again here because it's the easiest part of this plan to get subtly wrong during implementation.
2. **The hint is resource-level, not org-level — cross-border collisions are not fully solved.** The hint is computed once per resource (from the dataset page's own URL/HTML) and applied uniformly to every creator/affiliation/publisher/funder in it. A resource genuinely citing a foreign institution that happens to share a name with a domestic one (e.g. a Chilean-hosted dataset naming an Argentine "Instituto Nacional de Estadística," with Chile also having an org by that name) can go either way: if only the correct foreign org is a ROR candidate, the −15 penalty can drop it below threshold entirely (a match lost that would have succeeded pre-P0#1); if a same-named domestic decoy also exists, it can outrank the correct org when their raw scores are close (a real misattribution). The penalty only ever flips an outcome when the two candidates' names are already near-identical — a weak coincidental match never gets promoted over a strong correct one — but for the identical-name case specifically, this is a genuine, unresolved gap. Not fixed by this plan: the real fix is per-affiliation country detection (parsed from the affiliation string's own address, not the hosting page), out of scope here. Mitigated in practice by P0#2's override store (bypasses the heuristic entirely for known cases) and P0#4's provenance logging (makes a bad auto-attach auditable instead of silent).
3. **Identifier cache goes cold on deploy.** Once country enters `_make_key` (P0#1), every existing `~/.cache/gema/identifiers` entry stops matching (different hash). This is expected, not a bug — one cold resolution pass, then the 30-day TTL behaves as before. Document this in the PR description so it isn't mistaken for a regression when API call volume spikes briefly after deploy.
4. **P0#3 changes real output, not just internals.** Trusting ROR's own linked ISNI over the independent ISNI-SRU double-check will flip some matches from `status="review"` to `status="auto"` (see the corrected rationale above) — this needs an actual before/after diff on real data before merging, not just green tests (the tests themselves are being rewritten to match the new behavior, so they can't catch a bad call here).
5. **Overrides file must fail soft.** `config/overrides.yaml` (P0#2) should follow this subsystem's existing "never raise" philosophy (every client in `enrichers/` swallows errors and logs) — a missing, empty, or malformed overrides file should mean "no overrides applied," never a pipeline-aborting exception.

---

## Verification runbook

1. `make lint` / `make typecheck` — mypy strict on the new `extract_country`, `country` params, and `PipelineConfig` field.
2. `uv run pytest tests/test_identifier_resolver.py tests/test_fuzzy_matcher.py tests/test_ror_client.py tests/test_identifier_enricher.py -v` — subsystem-focused pass first, including the rewritten `TestMergeBothSources` assertions (P0#3).
3. `make test` — full unit suite.
4. `make test-regression` — confirms the identifier-cache key change (P0#1) doesn't touch the separate golden LLM-response cache; should still replay clean.
5. Manual: run `gema process` on 2-3 real Chilean-source inputs before and after, diff the `name_identifiers`/`affiliation_identifier`/`funder_identifiers` output directly — confirm P0#3's expected auto/review status shifts are the ones actually intended, not a surprise.
