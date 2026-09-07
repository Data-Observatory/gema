# CDIF/Croissant Pivot — Implementation Progress

Tracks execution of `docs/codata_mcp_croissant_cdifspecs.md`'s decision record. Updated as branches land. Not a decision record itself — see that file for the "why."

## Locked decisions

- **Enrichment architecture fork: option (A).** `enrichers/identifier_enricher.py`, `enrichers/doi_resolver.py`, `enrichers/pid_validator.py`, `output.py`, `exporters/dataverse.py` get retargeted to read CDIF field names directly off the CDIF-generated `MetadataDocument`. No DataCite-shaped intermediate representation reintroduced.
- Spec file lives at `docs/codata_mcp_croissant_cdifspecs.md` (renamed from root `specs.md`, commit on `feat/cdif-croissant-pivot-spec`).

## Branch

All of it lands on **`feat/cdif-croissant-pivot-spec`** (current branch) as progressive commits — no further branch stack. Steps below are work-order within this one branch, not separate PRs. Rename the branch before opening a PR if a more accurate name is wanted once scope is final (e.g. `feat/cdif-croissant-pivot`).

## Research findings (resolves/narrows several open questions)

**Q1 — CDIF vendoring source, resolved to a concrete candidate.** The real target is **`Cross-Domain-Interoperability-Framework/doc-corediscovery`** at commit `81c28260778426cc61302105fc7191b4db360bc9` (2026-05-16) — this is the *composite application profile* ("full discovery... human-facing content requirements"), not `profile-discovery` (a narrower module that only composes `cdifCore`). Files vendored: `schema.json`, `frame.jsonld`, `shacl.ttl`. **There is no standalone `context.jsonld` file** — `@context` is embedded directly in the schema and frame files. **Add a 4th vendored artifact**: `documents/CDIF-metadata-crosswalks-merged.xlsx` from the same commit — CDIF's own maintained DataCite↔schema.org crosswalk (150 rows), the strongest available source for the field mapping below, better than any third-party literature. Not yet copied into the repo; do this before or alongside Step 2's schema implementation.

Confirmed via the real schema: required floor is exactly `@id, @type, @context, schema:name, schema:identifier, schema:dateModified, schema:subjectOf` (matches spec §3.2/§5 verbatim) via `allOf[0].required`, **plus two conditional requirements**: `allOf[1]` requires `schema:license` OR `schema:conditionsOfAccess` (anyOf), and `allOf[2]` requires `schema:url` OR `schema:distribution` (anyOf). `CDIFDiscoveryProfile.output_model`/`validate_output` needs a Pydantic `model_validator` for this, not just a flat required-fields list.

**Correction (caught by a second research pass, Opus + web/primary-source verification): the schema declares 32 top-level properties, not 27.** The first pass read only `.properties` and missed 5 more declared inside `.allOf[3].properties`: `schema:measurementTechnique, schema:variableMeasured, schema:spatialCoverage, schema:temporalCoverage, dqv:hasQualityMeasurement`. These are genuine first-class CDIF Discovery properties (the vendored implementation guide titles that block "Properties added in Discovery Profile"), **not** an out-of-scope `profile-discovery`-only extension as the first pass wrongly claimed. Full corrected list (32): the 26 non-envelope properties from the original list (`@context, @id, @type, schema:name, schema:description, schema:identifier, schema:additionalType, schema:sameAs, schema:version, schema:inLanguage, schema:dateModified, schema:datePublished, schema:conditionsOfAccess, schema:license, schema:url, schema:distribution, schema:relatedLink, schema:publishingPrinciples, schema:keywords, schema:creator, schema:contributor, schema:publisher, schema:provider, schema:funding, prov:wasGeneratedBy, prov:wasDerivedFrom, schema:subjectOf`) plus the 5 just found (`schema:measurementTechnique, schema:variableMeasured, schema:spatialCoverage, schema:temporalCoverage, dqv:hasQualityMeasurement`).

**Q9 — Croissant top-level fields, resolved and corrected against the real spec.** Verified directly against `docs/croissant-spec-1.1.md` in `mlcommons/croissant` (commit `0e5dcb796dba285b396011638a68909c78a39664` — the last commit to actually touch that file as of the fetch date; an earlier citation of this pin wrongly named a commit that only touched `README.md`, caught and corrected 2026-09-04 — fetched 2026-09-04) rather than trusting the draft below it replaces. Required: `@context, @type ("sc:Dataset"), dct:conformsTo (aliased "conformsTo"), name, description, license, url, creator, datePublished, distribution`. Recommended: `keywords, publisher, version, dateCreated, dateModified, sameAs, sdLicense, inLanguage`. Croissant-specific (optional): `citeAs, isLiveDataset, sdVersion`. **Correction vs. the original draft**: `distribution` was filed under "Croissant-specific" (implying optional); the spec's "Modified and Added Properties" section states plainly that Croissant "modifies the meaning of [schema.org's `distribution`], and makes it required" — it belongs in the required set, not the optional one. Everything else in the original draft checked out unchanged.

## Q2 — Verified DataCite → CDIF field mapping (resolved, research-backed)

Full per-field mapping, verified against the real vendored schema, CDIF's own `CDIF-metadata-crosswalks-merged.xlsx` (150-row DataCite↔schema.org crosswalk in the same vendored commit — the authoritative source, used wherever it has an answer), the CDIF Implementation Guide, the real schema.org machine-readable vocabulary (not recalled), and DCMI Terms. One row per current DataCite field (`src/metadata_enricher/schemas/datacite.py`'s shapes), not per agent — assign to agents/waves when writing `config/agents.yaml` in Step 2.

| DataCite field | CDIF/JSON-LD target | Confidence |
|---|---|---|
| `resource.identifier`/`identifier_type` | `@id` (if resolvable URI) else `schema:identifier` (PropertyValue: `schema:propertyID`←type, `schema:value`, `schema:url`) | Verified |
| `resource.resource_type_general` | `@type` (array incl. `schema:Dataset`) | Verified |
| `resource.resource_type` | `schema:additionalType` | Verified |
| `resource.version` | `schema:version` | Verified |
| `resource.language` | `schema:inLanguage` | Verified |
| `resource.publication_year` | `schema:datePublished` | Verified |
| `resource.editor` | `schema:contributor` → `Role{roleName:"Editor"}` | Verified |
| `resource.maintainer` | `schema:maintainer` (Person/Org) — distinct from `subjectOf.maintainer` (metadata-record contact, don't conflate) | Verified term, inferred node |
| `resource.contact` | `schema:contributor` → `Role{roleName:"ContactPerson"}` | Verified |
| `resource.producer` | `schema:producer` | Verified |
| `resource.thumbnail` | `schema:relatedLink` → `LinkRole{linkRelationship:"thumbnail"}` | Verified |
| `titles` (main) | `schema:name` — **single-valued, see Constraint C1** | Verified |
| `titles` (Alternative/Subtitle/Translated/Other) | `schema:alternateName` | Verified |
| `descriptions` (Abstract) | `schema:description` — **single-valued, see C1** | Verified |
| `descriptions` (Methods) | `schema:measurementTechnique` | Inference (good fit) |
| `descriptions` (other types) | fold into `schema:description` or `dcterms:tableOfContents`/`schema:isPartOf` | Inference |
| `languages` | `schema:inLanguage` (first) + `dcterms:language` (overflow) — see C2 | Verified constraint |
| `dates[Created]` | `schema:dateCreated` | Verified |
| `dates[Updated]` | `schema:dateModified` (required floor) | Verified |
| `dates[Issued]` | `schema:datePublished` | Verified |
| `dates[Copyrighted]` | `schema:copyrightYear` | Verified |
| `dates[Available]` (embargo) | `schema:conditionsOfAccess` | Verified |
| `dates[Collected]` | `schema:temporalCoverage` | Verified |
| `dates[Accepted/Submitted/Valid/Withdrawn]` | `dcterms:dateAccepted`/`dateSubmitted`/`valid`/`schema:expires` | Inference per-term |
| `alternate_identifiers` | `schema:sameAs` — **identity assertions, minItems 1, see C6** | Verified |
| `related_identifiers` | `schema:relatedLink` → `LinkRole{linkRelationship←relation_type, target: EntryPoint}` — **typed relations, do not merge with sameAs** | Verified |
| `related_identifiers[IsDerivedFrom]` | `prov:wasDerivedFrom` (CDIF explicitly says use this, not `schema:isBasedOn`) | Verified |
| `related_identifiers[HasPart/IsPartOf]` | `schema:hasPart`/`schema:isPartOf` | Verified/flagged |
| `geo_locations` | `schema:spatialCoverage[]` → `Place{name, identifier, geo: GeoCoordinates\|GeoShape}` | Verified |
| `temporal_events` (frequency) | `dcterms:accrualPeriodicity` (not `schema:repeatFrequency` — that property's domain is `Schedule` only, out of domain here) | Inference on exact term, flagged |
| `subjects` | `schema:keywords[]` as `DefinedTerm{name, inDefinedTermSet, identifier, termCode}` | Verified |
| `categories` | `schema:about[]` (DefinedTerm) recommended over folding into keywords — CDIF's own crosswalk says `keywords`; `about` is semantically cleaner. **Judgment call, flagged for review.** | Flagged |
| `audiences` | `schema:audience`→`Audience{audienceType}` + `schema:educationalLevel` + `dcterms:mediator` + `dcterms:instructionalMethod` — all four are a verbatim DCMI-Terms lift, `dcterms` is already a required CDIF prefix. **Supersedes the earlier "fold into keywords" decision** — this preserves all 4 sub-fields instead of losing 3 of them. | Verified |
| `creators` | `schema:creator` → `{"@list":[Person\|Organization]}` — **object wrapping `@list`, not a bare array, see C4** | Verified |
| `creators[].contributor_type` | `schema:contributor` → `{"@type":["schema:Role"], "schema:roleName", "schema:contributor": <Person\|Organization>}` — **the actor nests inside the Role wrapper's own `schema:contributor` property, not a flat sibling; resolved Open Question #17, see Step 5.5/#17 writeup** | Verified |
| `publishers` | `schema:publisher` (single) + overflow → `schema:provider[]` — **single-valued, not an array, see C3** | Verified constraint |
| `rights.rights`/`rights_uri`/`rights_identifier` | `schema:license[]` (string\|`{@id}`\|`LabeledLink`) | Verified |
| `rights.rights_condition` | `schema:conditionsOfAccess` | Verified |
| `rights.rights_holder` | `schema:copyrightHolder` | Verified |
| `funding_references` | `schema:funding[]` → `MonetaryGrant{name, identifier, funder: Organization}` — **funder nests inside the grant, no top-level `schema:funder`** | Verified |
| `citations` | `dcterms:bibliographicCitation[]` (structured per-citation dict: title/volume/issue/pages/edition/conference, unchanged from the pre-#19 shape) — **not `schema:citation`, forbidden outright by the vendored `shacl.ttl` (`cdifd:citationProperty`, `sh:maxCount 0`); not `prov:wasDerivedFrom`** (that's input-data lineage, a different concept; citations are bibliographic). Resolved Open Question #19 — this row previously said `schema:citation[]` and was marked "Verified", which was wrong; see the #19 writeup for the correction and the kept-structured-vs-plain-string judgment call. | Corrected |
| `media_files` (file access) | `schema:distribution[]` → `DataDownload{contentUrl, encodingFormat, contentSize, spdx:checksum}` | Verified |
| `media_files[].variable_measured` | `schema:variableMeasured[]` → `PropertyValue` | Verified |
| `media_files[].measurement_technique` | `schema:measurementTechnique` | Verified |
| `media_files[].data_quality` | `dqv:hasQualityMeasurement` (needs `dqv` prefix) | Verified |
| `media_files[].provenance` | `prov:wasGeneratedBy` → `Activity{used:[...]}` | Verified |
| `media_files[].temporal_resolution` | `dcat:temporalResolution` | Verified |
| `media_files[].Collections` | `schema:includedInDataCatalog` → `DataCatalog` | Verified |
| `media_files[].physical_carrier` | drop (always literal `"digital"`, carries no info) | Verified |

### Hard JSON-Schema constraints the Pydantic model must respect

Found by directly parsing the vendored schema's actual types — missing these produces invalid documents silently:

- **C1** — `schema:name`/`schema:description` are `type: "string"`, single-valued. Multi-title/multi-description DataCite output needs a primary-value-wins strategy; route the rest elsewhere (`alternateName`, folded description). No language-tagged `{"@value","@language"}` objects — legal RDF, fails this JSON Schema.
- **C2** — `schema:inLanguage` is single-valued `string`. Overflow → `dcterms:language`.
- **C3** — `schema:publisher` is a single object (`anyOf`), not an array. gema's `publishers` is a list — only one survives as `publisher`, rest → `schema:provider` (which is an array).
- **C4** — `schema:creator` is an object wrapping `@list` (order-preserving), not a bare array — unlike `contributor`, which is a bare array. Easy to mix up.
- **C5** — `@context` requires `schema, dcterms, dcat, prov`. Richer forms need more: `spdx` (checksums), `geosparql`+`sf` (geometry), `time` (intervals), `dqv` (quality) — some with `const`-pinned URIs in `allOf[3]`, must be emitted verbatim.
- **C6** — `schema:sameAs` has `minItems: 1` — omit the key entirely when empty, don't emit `[]`.
- **C7** — nested `@type` values are arrays with a `contains` const (e.g. `["schema:Place"]`), not bare strings.

Two open judgment calls the mapping surfaces (not yet decided): **`categories` → `schema:about` vs. CDIF's own `keywords` suggestion** (about is cleaner but diverges from CDIF's crosswalk), and **`temporal_events` frequency → `dcterms:accrualPeriodicity`** (CDIF's crosswalk suggests `schema:repeatFrequency`, but that property is out-of-domain for a Dataset). Both are low-stakes and reversible later; default to the recommended (non-CDIF-crosswalk) choice unless told otherwise.

## Step 1 — Vendor CDIF artifacts — DONE (commit `78f0729`)

- [x] Resolve Open Question #1 — confirmed: `doc-corediscovery`@`81c28260778426cc61302105fc7191b4db360bc9`
- [x] Vendored `schema.json`, `frame.jsonld`, `shacl.ttl` under `src/metadata_enricher/schemas/cdif/discovery/` — no separate context.jsonld (doesn't exist upstream)
- [x] `VENDORED_SHA.txt` (SHA + repo URL + fetch date)
- [x] `tests/test_cdif_vendored_artifacts.py` — 12 tests, all passing: existence, JSON parses, shacl non-empty, SHA pattern, open-world shape (no closed top-level `additionalProperties`/`required`), required floor verified inside `allOf[0].required`
- [x] `make lint && make typecheck && make test` — clean (13 pre-existing baseline mypy stub errors only, 1016 passed/1 skipped/17 deselected)

## Step 2 — CDIF schema + pivot core

- [x] Resolve Open Question #2 — full verified field mapping in the "Q2" section above (research-backed via CDIF's own crosswalk spreadsheet + schema.org vocab + DCMI terms); two low-stakes judgment calls flagged but defaulted
- [x] Vendor `documents/CDIF-metadata-crosswalks-merged.xlsx` (4th artifact, found during Q2 research) — DONE, commit `0d2878e`
- [x] Resolve Open Question #3: `extra="allow"` on `output_model`, plus a `model_validator(mode="after")` hard-enforcing the required floor (`@id, @type, @context, schema:name, schema:identifier, schema:dateModified, schema:subjectOf`) and the two conditional groups (`schema:license` OR `schema:conditionsOfAccess`; `schema:url` OR `schema:distribution`) — raises if the floor/groups aren't satisfied, allows anything else through
- [x] `CDIFDiscoveryProfile` (`cdif_discovery.py`) — DONE, commit `9bb0aff`: name/version(read from `VENDORED_SHA.txt`)/output_model/`build_output_model` (cache+digest pattern)/`_NORMALIZER_DISPATCH` (generic shape-based normalizers, not per-field bespoke — see module docstring for why)/the required-floor `model_validator` (both conditional OR-groups). 54 tests, all passing.
- [x] JSON-LD envelope (`@context`/`@id`/`@type`/`dcterms:conformsTo`/`schema:dateModified`/`schema:subjectOf`) injected inside `merge_agent_results` — DONE; dead-link comment above `conformsTo` emission present (spec §8)
- [x] Resolve Open Question #5: yes, execute SHACL + JSON-LD framing in v1
- [x] Added `pyshacl`, `rdflib`, `pyld` to `pyproject.toml` — DONE, commit `8621580`
- [x] SHACL (`shacl.ttl`) as a non-blocking conformance check and JSON-LD framing (`frame.jsonld`) via `pyld` — DONE, see Step 6 below. `validate_output` itself still only runs the Pydantic required-floor check (unchanged, by design) — SHACL runs as a separate method (`check_shacl_conformance`), wired into `pipeline.py` as its own opt-in step, not folded into `validate_output`.
- [x] `schemas/__init__.py`: **`CDIFDiscoveryProfile` is now the SOLE registered schema** — DONE, commit `f3bdf26`. `DataCiteSchema46` deregistered (still importable from `schemas.datacite` for exporter/migrate.py use).
- [ ] `DataCiteSchema46` singleton pattern decided for post-deregistration reuse (avoid re-parsing 505KB IANA JSON per use) — still open, relevant once `exporters/datacite.py` (Step 3) instantiates it repeatedly
- [x] Blast-radius retarget (option A, locked): `identifier_enricher.py`, `doi_resolver.py`, `pid_validator.py`, `output.py`, `exporters/dataverse.py` → CDIF field names — DONE, commit `e59ed53`
- [x] `config/agents.yaml`: `schema_name: cdif-discovery`, all 5 agents' `fields:`/`context_fields:`/prompts rewritten to CDIF vocabulary — DONE, commit `f3bdf26`. Actor-field reorg: resource-level editor/contact/producer moved into `creators_publishers` as `schema:contributor` entries with roles, rather than staying on a "resource" grab-bag field (CDIF has no such field) — a real, deliberate reshaping, not silent. `temporal_events`/`Collections`/`publishing_principles` dropped from v1 scope (no clean CDIF home or no source signal); flagged in Backlog.
- [x] Resolve Open Question #13: DataCite closed vocabularies (license/funding taxonomies, Chilean affiliation hierarchy table) stay in `config/agents.yaml`'s prompts as-is — CDIF's `schema:license`/`schema:funding` shapes don't require different vocab, just different key names, so nothing needed to move to `exporters/datacite.py`.
- [x] `config/migrate.py`: kept `"datacite-4.6"` hardcoded, added comment + `logger.warning` + docstring Notes update + test — DONE, commit (docs(config) migrate.py warning commit)
- [x] `record_golden.py`: fixed `-s/--schema` (was fed only to `OutputWriter`, ignoring `config.schema_name` — same bug independently found in `cli.py`'s `process --schema`, both fixed) — DONE, commit (fix(cli) --schema commit)
- [x] Update: `tests/test_cli.py`, `test_pipeline_integration.py`, `test_datacite_schema.py`, `test_dataverse_export.py`, `test_config_migration.py` — DONE. `test_preflight.py` checked: uses its own self-contained `_MockSchema` + private `SchemaRegistry` instance, never touches the real registry, needs no change.
- [x] `visor/tests/{test_bootstrap,test_glue}.py` — 4 datacite-4.6 fixtures fixed, DONE, commit `e40d0c7`. Full visor suite (185 tests) green; `ruff check visor/` clean; `mypy visor --exclude visor/tests` shows 37 pre-existing import-resolution errors, confirmed identical with all this session's changes stashed (local-environment artifact, unrelated to this work — see CLAUDE.md's own caveat that local visor typecheck doesn't mirror CI).
- [x] Snapshot pre-flip baseline: `config/legacy/agents_datacite46.yaml`, `tests/fixtures/golden_datacite46_baseline/{inputs,expected,cache}` — DONE, before overwriting live fixtures, so spec §9's A/B diagnostic retains a baseline.
- [x] `make record-golden` — DONE, real API calls (opencode/deepseek-v4-flash + real ROR/ISNI/DOI/Crossref calls), all 6 inputs succeeded, output quality verified by hand (correct envelope, real institutional actor extraction, correctly-gated identifier enrichment, rich measurementTechnique/variableMeasured/dqv/prov extraction from prose). `test_regression.py`'s 6 checks now pass via cache-replay.
- [x] End-to-end test: confirmed via the real recording run's logs — CDIF-generated documents did receive real ROR/ISNI resolution attempts (correctly withheld when ambiguous, per `identifier_enricher.py`'s gate), DOI resolution ran, and `TestAgainstRealGoldenFixture` (re-enabled, real assertions) confirms a non-degenerate Dataverse export from the real recorded output.
- [x] New `tests/test_cdif_discovery_schema.py` — DONE in the earlier schema commit (`9bb0aff`), 54 tests. Registry-contents meta-test included (`TestExporterOnlyNoLongerRegistered` in `test_datacite_schema.py` + `TestRegistryIntegration` in `test_cdif_discovery_schema.py`).
- [x] SHACL conformance check + JSON-LD framing — DONE, see Step 6 below.
- [x] Docs: root `AGENTS.md`, `CLAUDE.md`, `schemas/AGENTS.md` (+ new `cdif/` subtree entry, fix stale line refs), `docs/CONFIGURATION.md` (`schema_name` example + dead-URI caveat), `README.md`, `scripts/README.md`, `src/metadata_enricher/AGENTS.md`, `src/metadata_enricher/config/AGENTS.md` — DONE (2026-09-03). `ONBOARDING_BIBLIOTECARIA.md` explicitly excluded (out of scope, see the user's own instruction — file no longer exists as of 2026-09-04, cause unclear, not investigated further since the outcome matches what was asked).
- [x] Resolve Open Question #14 (`visor/session_settings.py` persisted-override migration/reset) — checked, **not actually a gap**: `visor/settings.py::apply_agent_overrides` already skips (never raises on) an override whose agent ID or provider name no longer exists in the loaded config, by design (see that function's own docstring). Agent IDs and provider names didn't change in the pivot, so a pre-pivot persisted override keeps working unchanged. No migration/reset path needed.
- [x] Verify: `make lint && make typecheck && make test`, `ruff check visor/`, `mypy visor --exclude visor/tests`, `make test-visor`, `make test-regression` — all done, all green (mypy visor's 37 errors are pre-existing/unrelated, see above).
- [ ] Manual live identifier-resolution check + `make live-eval` before any `dev`→`main` PR — not yet run; the record-golden run above (and the Step 5.5 re-recording) exercised real identifier resolution incidentally but this is a separate, more thorough check called out by CLAUDE.md's live-test rule. Not blocking — user has explicitly deferred all PR-timing decisions to themselves (2026-09-04).

**Step 2 is functionally complete**, and its two originally-open non-blocking items (docs cleanup, visor settings migration) are now both closed too. The CDIF generation pivot works end to end against a real provider, with real identifier enrichment. Test counts have moved since this line was first written (Steps 3-5.5 each added coverage) — see the Standing rules section for the current count rather than trusting a number here going stale again.

## Step 3 — DataCite exporter — DONE (commits `6413b62`, `ae9539d`, `f666c51`, `428e4be`)

- [x] `exporters/datacite.py`: real CDIF→DataCite mapping table (Q2 table read in reverse — `_build_resource`/`_build_titles`/`_build_creators`/`_build_publishers`/etc.), `DataCiteExportResult{datacite_json, warnings, token_usage}`, delegates to `DataCiteSchema46` normalizers/`validate_output` only as the last step (never copy-pasted normalizer logic) — commit `6413b62`
- [x] Resolved Open Question #8 (LLM call scope): **none, pure crosswalk** — `to_datacite_json(document)` makes no LLM call, `token_usage` always zero, kept only for shape-parity with `exporters/dataverse.py`
- [x] `DataCiteSchema46` singleton (Open Question raised in this same section originally): module-level `_datacite_schema_instance` + `_get_datacite_schema()` accessor in `exporters/datacite.py` — avoids re-parsing the ~505KB bundled IANA MIME snapshot on every export call now that `DataCiteSchema46` is no longer registry-cached
- [x] `exporters/__init__.py` re-export: `DataCiteExportResult`, `to_datacite_json` (alongside the existing Dataverse exports, not clobbered)
- [x] `tests/test_datacite_export.py` — 38 tests, all **CDIF-shaped synthetic fixtures** (CURIE-keyed `MetadataDocument.set_field` dicts) plus a real-world check against the committed `tests/fixtures/golden/expected/sample_input01.json`. Explicit `"Collections"` capitalization end-to-end regression test (`TestMediaFilesAndCollectionsCapitalization::test_collections_capitalization_survives_end_to_end`). Also covers: missing/empty fields degrade to warnings not crashes, C3 (`schema:publisher`+`schema:provider` overflow → DataCite `publishers` list) and C4 (`schema:creator`'s bare-list-vs-`{"@list":[...]}`-wrapper ambiguity — see judgment call below) reversals, `schema:sameAs`/`schema:relatedLink` staying distinct (`alternate_identifiers` vs `related_identifiers`), and the envelope fields (`@id`, `schema:dateModified`, `schema:datePublished`, `@type`) mapping back into `resource.identifier`/`resource.resource_type_general`/`dates`/`resource.publication_year` — commit `ae9539d`
- [x] New `exporters/AGENTS.md` documenting both `dataverse.py` and `datacite.py` (package contract, what this package is *not*, field-mapping judgment calls, testing conventions, anti-patterns) — commit `f666c51`
- [x] `make lint && make typecheck && uv run python -m pytest -m "not live" -q` — all green (1106 passed, 1 skipped, 17 deselected; mypy: 13 pre-existing baseline stub-only errors, none newly introduced by this file)

**Resolved (2026-09-04, post-Step-3/4 merge)**: the `schema:creator`/C4 gap flagged above (and independently by the Step 4 agent) has been fixed at the source. `CDIFDiscoveryProfile.merge_agent_results` now wraps `schema:creator` into `{"@list": [...]}` right after the agent-merge loop, before envelope injection — agents still emit a plain list (the natural Instructor/structured-output shape); the wrap is a pure JSON-LD serialization step applied once, after generation, so it never leaks into agent prompts. `types.jsonld_list_unwrap()` is the shared reader every consumer now goes through: `enrichers/identifier_enricher.py::_enrich_creators`, `enrichers/doi_resolver.py::_backfill_creators` (which also now wraps when backfilling from Crossref, for consistency regardless of which code path populated the field), and `exporters/dataverse.py`'s two creator-reading sites were all silently broken by the wrap before this fix (iterating a `{"@list": [...]}` dict iterates its keys, not entries) and are now fixed. `exporters/datacite.py`'s `_creator_list()` and `exporters/croissant.py`'s `_as_entry_list()` — already defensive dual-shape readers from Steps 3/4 — now delegate to the shared `jsonld_list_unwrap` instead of duplicating the logic. `pid_validator.py` needed no change (its identifier walk is fully generic over nested dicts/lists). All 6 golden fixtures re-wrapped in place (structural change only, no re-recording). New coverage: `test_cdif_discovery_schema.py::TestMergeAgentResults` (wrap + empty-list wrap), `test_identifier_enricher.py`/`test_dataverse_export.py` (wrapped-input cases). Full suite green: 1156 passed, 1 skipped.

## Step 4 — Croissant exporter

- [x] Resolve Open Question #9 (Croissant top-level field mapping — direct spec check): verified against `docs/croissant-spec-1.1.md` in `mlcommons/croissant`, commit `0e5dcb796dba285b396011638a68909c78a39664` (corrected 2026-09-04 from an earlier, wrong pin — see the Q9 paragraph above), fetched 2026-09-04. Verified field list (corrected from the earlier draft — see the Q9 paragraph above for what changed and why): **Required** — `@context, @type ("sc:Dataset"), dct:conformsTo (aliased "conformsTo"), name, description, license, url, creator, datePublished, distribution`. **Recommended** — `keywords, publisher, version, dateCreated, dateModified, sameAs, sdLicense, inLanguage`. **Croissant-specific (optional)** — `citeAs, isLiveDataset, sdVersion`.
- [x] `exporters/croissant.py`: top-level Dataset fields mapped from the CDIF-generated document per the verified list above; `recordSet` is absent from the output entirely (not an empty list) — a documented placeholder gap in the module docstring, blocked on the structure-fetcher enricher (see Backlog below, Open Questions #10-12). `sdLicense`, `citeAs`, `isLiveDataset`, `sdVersion` also left unmapped in v1 — no CDIF Discovery field to source them from, documented in the module docstring rather than silently dropped.
- [x] `exporters/__init__.py` re-export — `CroissantExportResult`, `to_croissant_json` added alongside the existing Dataverse exports.
- [x] `tests/test_croissant_export.py` from CDIF-shaped synthetic fixtures — 45 tests: per-field fallback/omission behavior, the required-floor per the verified list, checksum-algorithm detection by digest length (sha256/md5, with a warned no-op for unrecognized lengths like sha-1), `recordSet` never appearing under any input, and a pass against every real committed golden fixture (`tests/fixtures/golden/expected/*.json`).
- [x] `make lint && make typecheck && make test` (via `uv run python -m pytest -m "not live" -q`, per this session's environment) — all clean; mypy's 13 pre-existing baseline errors unchanged, no new ones from `croissant.py`.

## Step 5.5 — Nested-shape CURIE-key fix (2026-09-04, post-Step-4)

**Bug found while wiring up a SHACL conformance check (separate follow-up, not built here):** every *nested* object inside a top-level CDIF field used plain English-ish keys (`{"name": "Jane Doe", "given_name": "Jane"}`) instead of CURIEs (`{"schema:name": "Jane Doe", "schema:givenName": "Jane"}`). Top-level field names were already correct CURIEs — only what's nested *inside* them (a creator/organization's `name`, an identifier's `propertyID`/`value`, a related-link's `target`, a spatial-coverage `Place`, a funding grant's `funder`) was bare. Proven against a real recorded example (`tests/fixtures/golden/expected/sample_input06.json`): converting it to RDF via real JSON-LD tooling (rdflib/pyld, which only resolve properties declared in `@context`) silently dropped **both** of its creators' names and produced a false "no identifier" reading despite a real DOI being present, because a bare key at a nested level isn't declared anywhere in `@context` and gets discarded during expansion.

Fixed everywhere this shape is produced, read, or hand-built: `enrichers/identifier_enricher.py` (module docstring's shape convention rewritten to CURIE, all Person/Organization/PropertyValue construction and reads), `enrichers/doi_resolver.py` (Crossref backfill), `enrichers/pid_validator.py` (`_walk_scheme_pairs`/`extract_pids` now search for `schema:value`/`schema:propertyID`), `output.py` (DOI-based filename derivation off `schema:identifier`, missed by the original blast-radius list in Step 2 — found this session by grepping for `schema:identifier` reads repo-wide), `exporters/dataverse.py`, `exporters/datacite.py`, `exporters/croissant.py`, `schemas/cdif/discovery/cdif_discovery.py` (`_normalize_dict_list`/`_normalize_single_dict`'s bare-string-to-dict fallback, `_derive_id`'s `schema:identifier` walk), `config/agents.yaml`'s embedded prompt examples for all 5 agents (the highest-value fix — without it, real LLM generation keeps producing the old bare shape regardless of what the code expects), all 6 golden fixtures, and every test file building/asserting these shapes.

Also fixed in the same pass, since every nested typed object's construction site was already being touched: **C7** (nested `@type` as a one-element array, e.g. `["schema:Person"]`, not a bare string) — this also fixed a real pre-existing bug in `exporters/croissant.py`'s `_person_or_org`, which compared `entry.get("@type") == "schema:Person"` as a bare scalar and would have silently misclassified every Person as an Organization once `@type` became an array. The fix is centralized in a new shared `types.first_type_label()` helper (handles both a bare string and an array, extracts the CURIE's local name), used by `identifier_enricher.py`, `datacite.py` (replacing its private `_first_type_label`/`_strip_curie`), and `croissant.py` — the same "extract once, share" precedent `jsonld_list_unwrap` set earlier this session.

**Deliberate gema extensions, not vendored-schema properties** (documented at the point of use, not "fixed" into something they're not): `schema:givenName`/`schema:familyName` on Person (real schema.org terms this profile just doesn't reference — used for citation formatting and ORCID matching), `schema:email` on Person/Organization/contributor entries (same reasoning). `matched_via`/`confidence`/`status` inside a `schema:identifier` PropertyValue entry stay bare on purpose — `identifier_enricher.py`'s own audit trail, deliberately outside the JSON-LD graph, not meant to round-trip through JSON-LD tooling.

**Explicitly left un-renamed, either genuinely out of scope or too risky to guess at under this pass:**
- `schema:audience`'s `audience`/`mediator`/`education_level`/`instructional_method` and `schema:citation`'s DataCite-shaped keys (`title`/`volume`/`start_page`/...) — neither has a vendored-schema shape at all; both are deliberate DataCite-key pass-throughs (see `exporters/datacite.py`'s own comments), not a CURIE-vs-bare question.
- `schema:conditionsOfAccess`'s `condition`/`date` and `schema:distribution`'s `checksum`/`temporal_resolution`/the `{"size","unit"}` shape inside `schema:contentSize` — none of these keys correspond to a real property on the vendored `LabeledLink`/`DataDownload` defs (checksum in particular wants a nested `spdx:checksum{@type, algorithm, checksumValue}` object, a structural change, not a rename). Renaming them would mean guessing at a CURIE the spec doesn't actually offer; left bare rather than inventing one.
- Two real, additional shape mismatches this pass surfaced but did **not** resolve — see Open Questions #16 and #17 below.

New coverage: `types.first_type_label()` gets exercised transitively through every exporter/enricher test that constructs a Person/Organization with an array `@type`; no new dedicated test file, consistent with `jsonld_list_unwrap`'s own precedent (tested via its callers, not standalone).

**Two new open questions this pass surfaced, deliberately not resolved (see log below):**

- **Nested `schema:identifier` cardinality (Q16).** The vendored schema models `Person.schema:identifier`, `Organization.schema:identifier`, and `MonetaryGrant.schema:identifier` as *singular* (one `Identifier` object or a string) — not an array. gema's own convention, and `enrichers/identifier_enricher.py`'s actual behavior, always builds this as a *list* at every nesting level, so a resolved organization can carry both a ROR and an ISNI at once without one silently overwriting the other (a deliberate "never drop a resolved identifier" decision made earlier this session). This is the same shape of deviation as the already-resolved top-level C3 constraint (`schema:publisher` singular + `schema:provider[]` array overflow) but one level deeper, and the vendored `Person`/`Organization` defs even define a `schema:sameAs` array right next to the singular `schema:identifier`, described as "other identifiers" — suggesting CDIF's own intended resolution for multi-identifier cases is that same singular-plus-overflow pattern, not a plain array. Not changed by this pass — cardinality is out of scope for a key rename, and gema's list-based behavior is deliberate, not accidental.
- **`schema:contributor`'s Role wrapper (Q17).** Q2's mapping table (row: `creators[].contributor_type`) already said `schema:contributor` → `Role{roleName}`, and the vendored `schema.json` confirms it: a contributor entry that carries a role is modeled as `{"@type": ["schema:Role"], "schema:roleName": ..., "schema:contributor": <Person|Organization>}` — the actor being described is nested *inside* the Role wrapper's own `schema:contributor` property, not a flat sibling key. gema's actual contributor entries (`config/agents.yaml`'s `creators_publishers`/`media_files` prompts, `enrichers/identifier_enricher.py`, `exporters/dataverse.py`, `exporters/datacite.py`) instead read/write a flat `{"schema:name": ..., "role": ..., "schema:email": ...}` shape — a real structural mismatch, not just a missing CURIE prefix (the vendored schema's `anyOf` for `schema:contributor` does allow a bare Person/Organization/`{@id}` with **no** role at all, but has no bare-string-role alternative once a role is being expressed — only the full Role wrapper). Deliberately not restructured by this pass, the same way C3/C4 were flagged-not-fixed before eventually being resolved in a later, dedicated pass: doing so is a shape change (nesting, not renaming) that touches every reader (`_build_dataset_contact`, `_build_resource`'s `_RESOURCE_ROLE_MAP` loop, `_build_creators`'s leftover-contributor loop) and deserves its own review, not a side effect of a key-rename pass. `role` is therefore still read/written bare everywhere in this codebase, flagged inline at each site touched this session.

## Step 6 — SHACL conformance check + JSON-LD framing (2026-09-04, post-Step-5.5)

Built `CDIFDiscoveryProfile.check_shacl_conformance(doc) -> list[str]` and
`.frame_output(doc) -> dict[str, Any]` (`schemas/cdif/discovery/cdif_discovery.py`).
Both were genuinely blocked until Step 5.5 landed (see that section) — before
the CURIE-key fix, converting a real document to RDF silently dropped data,
which would have made this check's results meaningless (false negatives
read as "conformant" only because the graph was empty of the properties
that mattered). Re-verified after Step 5.5: converting `sample_input06.json`
to RDF went from 50 triples (both creators' names missing, a real DOI read
as "no identifier") to 95 triples with both names present, using rdflib +
pyld directly against the document's own emitted `@context` — no extra
mapping needed.

**`check_shacl_conformance`**: serializes `doc.fields` to JSON, parses via
`rdflib.Graph(...).parse(format="json-ld")`, then
`pyshacl.validate(..., shacl_graph=<vendored shacl.ttl, loaded via
importlib.resources>, advanced=True)` — `advanced=True` is required because
several vendored shapes use `sh:SPARQLTarget`. Never raises (wrapped in a
broad `except Exception`, logs a warning, returns `[]` on any
infrastructure failure). On a real conformance failure, returns one
human-readable string per `sh:ValidationResult` (message + shape + focus
node), never the raw Turtle report.

**`frame_output`**: `pyld.jsonld.frame(doc.fields, <vendored frame.jsonld>)`.
Never raises — degrades to a `deepcopy` of `doc.fields` on any failure.

**Wiring decision**: `check_shacl_conformance` **is** wired into
`pipeline.py` as a new, non-blocking post-merge step mirroring the
existing PID-validation step, gated behind a new
`PipelineConfig.validate_shacl_conformance` flag, **default `False`**.
Rationale: every real recorded golden fixture fails this check today (see
findings below), mostly for reasons outside gema's direct control —
defaulting it on would flood every existing user with warnings they have
no way to act on yet. `frame_output` stays an **available-but-uncalled
utility method**, the same status `validate_output()` itself already has
— nothing in gema consumes CDIF's canonical framed shape yet (no output
writer, no exporter reads it).

**Findings from running against all 6 real golden fixtures**
(`tests/fixtures/golden/expected/sample_input0{1..6}.json`): all 6 return
non-empty `check_shacl_conformance` results (4/6/14/5/5/8 respectively —
these are SHACL *results* of any severity, not all `sh:Violation`; see
the note below the table), and every one is real and explicable — not
JSON-LD-conversion noise (that class of false positive was exactly Step
5.5's bug, already fixed; confirmed by reading the actual `shacl.ttl`
shape definitions behind each one, not just trusting the message text).
**Correction (2026-09-04, caught on review): the first write-up of this
section named 3 causes; there are actually 10 distinct shapes, not the
"9" a first correction pass also miscounted.** Full account:

| shape | fixtures hit | cause |
|---|---|---|
| `metadataProfileProperty` | all 6 | missing `dcterms:conformsTo`'s `cdif/core/1.0` value (see below) |
| `resourceIdentifierProperty` | all 6 | nested `schema:identifier` entries carry no `@type` |
| `rightsProperty` | all 6 | nested `schema:license` entries carry no `@type` (and some also have an empty `schema:url`) |
| `accessProperty` | 01,02,04,05,06 | fails the `schema:url`\|`schema:distribution` OR-group (see below) |
| `datePublishedProperty` | 02,04,05,06 | — |
| `contributorProperty` | 03 (×2), 06 | — |
| `distributionProperty` | 03 (×2) | — |
| `relatedResourceProperty` (target not `schema:EntryPoint`) | 03 (×6), 06 (×2) | — |
| `nameProperty` (empty `schema:name`) | 02 | — |
| `citationProperty` | 03 | **not a gema bug — a real conflict with Q2's own mapping, see Open Question #19 below** |

`check_shacl_conformance` returns every `sh:ValidationResult` regardless
of severity (`sh:Violation`/`sh:Warning`/`sh:Info`), stripped down to a
plain message string with no severity label — the vendored `shacl.ttl`
carries 18 `sh:Info` and 10 `sh:Warning` shapes alongside its
`sh:Violation` ones, and `citationProperty` specifically is `sh:Info`
severity (an advisory, not a hard violation, though "forbidden outright"
per `sh:maxCount 0` is still an accurate description of the rule itself).
The per-fixture counts above (4/6/14/5/5/8) are correct as "SHACL results
found", not as "hard violations found" — a real distinction the method's
current `list[str]` return type can't express. Worth a future decision:
either surface severity in the return type, or filter to `sh:Violation`
only for the non-blocking-warning use case `pipeline.py`'s wiring assumes.

- **Every fixture** is missing `dcterms:conformsTo`'s
  `https://w3id.org/cdif/core/1.0` value on its `schema:subjectOf` node —
  the vendored shapes require *both* the core and discovery conformance
  URIs (`cdifd:metadataProfileProperty`), but `CDIFDiscoveryProfile`
  only ever emits the discovery one (`_inject_envelope`, §8's dead-link
  decision covers the discovery URI only). Worth a follow-up: either emit
  both URIs, or accept this as a known, permanent gap and document it
  alongside the existing dead-link note.
- Nested `schema:identifier`/`schema:license` entries carry no `@type`,
  so SHACL's `sh:class schema:PropertyValue` (etc.) checks can't recognize
  them as typed nodes — a real, gema-controlled gap (these entries are
  built without an explicit `@type` key anywhere in `identifier_enricher.py`/
  `config/agents.yaml`'s prompts), not attempted to be fixed here (out of
  scope — this pass built the check, not a campaign to make fixtures pass
  it).
- **All 6 fixtures, not just `sample_input06.json` as first written here,
  fail `CDIFDiscoveryOutputModel`'s own required-floor `model_validator`**
  (confirmed by calling `validate_output()` directly on each): every
  fixture fails `license|conditionsOfAccess` except `sample_input01.json`
  (which has a license but fails the `url|distribution` group instead),
  and `sample_input02.json` additionally fails the base floor
  (`schema:name`/`schema:identifier` both effectively empty in that
  recording). Since `validate_output()` is never wired into `pipeline.py`,
  none of this is currently caught by anything. The license/conditionsOfAccess
  side of this is a data gap in these specific recordings, not a structural
  one; the url/distribution side has a structural cause — see next bullet
  and Open Question #20.
- **The `url|distribution` OR-group failure has a structural cause, not
  just missing data in these 6 recordings**: `schema:url` does not appear
  in *any* agent's `fields:` list in `config/agents.yaml` — nothing in
  `src/` ever writes it at the top level. The `07b417b` fix that taught
  `exporters/datacite.py` to read `schema:url` as an identifier fallback
  is correct but currently unreachable from real generated output; only a
  hand-built document can exercise it. `ResourceDescription.url` (always
  present on input) would satisfy this OR-group for free if injected
  during `_inject_envelope`, but that's a real design decision (is the
  *input* URL an acceptable stand-in for a *documented* landing page?),
  not made here. See Open Question #20.

None of the above was "fixed" here — per this session's scope, finding and
reporting these is the deliverable; forcing the fixtures/generation to
conform is a separate, future decision.

New tests: `tests/test_shacl_and_framing.py` (22 tests) — a hand-built,
real-shapes-verified conformant fixture (iteratively checked against the
actual vendored `shacl.ttl`, not asserted on faith), a real violation from
stripping one required field, malformed/garbage input never raising for
both methods, JSON-LD framing round-tripping every real golden fixture
without losing data, and framing degrading to an unchanged copy on
failure. Plus `tests/test_pipeline_integration.py::TestPipelineShaclValidation`
(3 tests) covering the opt-in pipeline wiring: disabled by default,
surfaces real violations as warnings when enabled, and an exception from
the check itself is caught, not propagated.

Also added `pyld` to `pyproject.toml`'s `[[tool.mypy.overrides]]`
(`ignore_missing_imports`, mirroring the existing `diskcache.*` entry) —
`pyld` ships no type stubs; `rdflib`/`pyshacl` both ship `py.typed` and
needed no override.

`make lint && uv run python -m mypy src/ scripts/ && uv run python -m pytest -m "not live" -q` —
all green (1191 passed, 1 skipped, 17 deselected). Note: in at least one
local environment this session ran in, the bare `uv run mypy ...` console
script resolved to an unrelated global `mypy` installation instead of the
project's own venv (a broken `.venv/bin/mypy` shebang / `PATH` quirk, not
a project issue) — `uv run python -m mypy ...` is the reliable invocation
if that's ever seen again; it reports mypy strict-mode clean (0 errors)
against everything this step touched.

### Backlog cleanup (2026-09-04, same session as Step 6)

Four smaller, concrete backlog items fixed alongside Step 6 (each its own
commit):

- **`exporters/datacite.py` test coverage**: added real tests for the 5
  previously-untested mapped fields (`schema:spatialCoverage`→`geo_locations`,
  `schema:keywords`→`subjects`, `schema:about`→`categories`,
  `schema:audience`→`audiences`, `schema:citation`→`citations`) —
  `temporal_events` already had coverage from an earlier commit this
  session. Also tightened `TestAgainstRealGoldenFixture` to assert real
  mapped values for `keywords`/`about`/`audience`/`spatialCoverage` from
  `sample_input01.json` (confirmed populated first), not just
  titles/creators/publishers/language/identifier/rights.
- **`test_croissant_export.py`**: converted the single-for-loop
  real-golden-fixture test to `@pytest.mark.parametrize` over all 6 files
  with real per-fixture expected values (name, creator names, license) —
  including `sample_input02.json`, a genuinely degenerate recording (no
  name/creator/license/identifier at all) whose expectations assert the
  documented fallback behavior rather than a fabricated value. Added
  `TestMalformedInputNeverRaises`, mirroring
  `test_datacite_export.py::test_malformed_types_never_raise`, which
  croissant had no equivalent of. Flagged a double-prefixed ROR URL found
  in `sample_input04.json`/`sample_input05.json`'s fixture data as
  out-of-scope for this change — **fixed in the Opus validation follow-up
  below**, where the actual blast radius turned out to be 4 fixtures/8
  occurrences, not 2.
- **`schema:measurementTechnique` double-mapping**: was written to both
  `descriptions[Methods]` and every `media_files[].measurement_technique`
  on the reverse mapping, duplicating the same fact on round-trip.
  Decision: `media_files[].measurement_technique` (Q2: "Verified") wins
  whenever `schema:distribution` is non-empty; `descriptions[Methods]` is
  now a fallback, not a duplicate — it only fires when there's no
  distribution to attach the technique to, preserving real data for
  documents shaped like the real recorded `sample_input06.json`
  (measurementTechnique populated, no distribution) instead of losing it.
- **Warning-discipline inconsistency**: `_build_publishers` now warns
  when both `schema:publisher` and `schema:provider` are empty (DataCite's
  own spec makes publisher mandatory, matching how `_build_creators`/
  `_build_titles` already warn on their own required-field misses).
  `_build_subjects`/`_build_categories`/`_build_audiences`/`_build_citations`
  stay silent on a deliberate judgment call — all four map optional
  DataCite fields, and an empty result is a normal outcome, not dropped
  data. Documented inline at each site.
- **DOI double-prefix risk in `exporters/croissant.py`'s `_build_url`**:
  added a guard (skip the `https://doi.org/` prefix if the DOI value
  already starts with `http://`/`https://`) and reordered to prefer the
  identifier entry's own `schema:url` before falling back to constructing
  one from the bare DOI value.

Full verification suite green after all of the above (see the Docs
section's own instructions and this doc's own "must pass" checks):
`ruff check`, `mypy` (via `python -m mypy`, see the note above), the
full `-m "not live"` suite, `-m regression`, and the visor suite.

### Opus validation follow-up (2026-09-04, same session)

An Opus review of the 18 commits from Step 5.5 through Step 6 found 5 more
real bugs and several doc-accuracy issues, all fixed the same session:

- **`schema:measurementTechnique` fallback gated on the wrong predicate**
  (a real regression introduced by the Step 6 fix above): `_build_descriptions`
  checked raw truthiness of `schema:distribution`, but `_build_media_files`
  applies a further filter (dict entries carrying `schema:contentUrl`)
  before it emits anything. A distribution list present but missing
  `schema:contentUrl` on every entry (reachable — `CDIFDiscoveryProfile`'s
  own `_normalize_dict_list` produces exactly this from a bare-string
  distribution) silently dropped the technique from *both* branches at
  once, with no warning. Fixed by extracting `_has_usable_distribution()`
  and gating both places on it; `_build_media_files`'s own warning
  condition uses the same check now, so this case is no longer silent
  either.
- **ROR URL double-prefixing in `enrichers/identifier_enricher.py`**: ROR's
  own API returns `id` as an already-full URI, but `_identifier_entries`/
  `_enrich_affiliations`/`_enrich_publisher` unconditionally prefixed it
  again. Real blast radius (not the 2-fixture estimate in the Backlog
  cleanup note above): **4 of 6 committed fixtures, 8 occurrences total**.
  Fixed with a shared `_scheme_url()` helper that no-ops when the value is
  already a full URL; the 8 malformed values in the committed fixtures
  were corrected in place (mechanical string fix — the value was
  known-wrong, not re-derived, so no live re-recording needed).
- **Same DOI double-prefix bug the Step 6 cleanup fixed in
  `croissant.py`'s `_build_url`, missed in `exporters/dataverse.py`'s
  `_build_alternative_url`** — same file range, same session, one of two
  call sites fixed. Now fixed there too, plus prefers the identifier
  entry's own `schema:url` before constructing one.
- **`exporters/datacite.py`'s `media_files[].sizes` passed `schema:contentSize`
  through raw**: DataCite's `sizes` field is a list of formatted strings;
  the CDIF-generated shape (a dict, or a list of dicts) was never
  normalized, unlike the equivalent fix already applied to
  `exporters/croissant.py`'s `_build_distribution`. Fixed with a
  `_content_size_strings()` helper.
- **Visor's Agents-tab config download/upload silently dropped
  `validate_shacl_conformance`**: `_download()` serializes the whole
  `PipelineConfig` (`model_dump`), but `_handle_upload()`'s manual
  field-by-field copy-back stopped at `validate_pids_live` and never
  picked up the newer flag — an uploaded config with it set would
  silently revert to the default the moment it was applied. Fixed by
  adding the missing line (same fragile-by-construction pattern flagged
  in a new inline comment, not restructured here).

Also flagged, not fixed: `config/agents.yaml`'s `media_files` prompt
describes `schema:contentSize` as always a single dict when populated,
but its own worked example shows a list-wrapped dict instead — a real
prompt-wording inconsistency. Attempted a wording fix here and reverted
it immediately: `agents.yaml`'s prompt text is part of the LLM
response-cache key (`cache.py:_make_key`), so *any* edit to it invalidates
every cached fixture response for that agent — the regression suite
started failing (`dqv_quality_measurement` field, live call attempted,
rejected) the moment the wording changed, even though nothing about the
generated *code* changed. Not worth a live re-record for a wording-only
fix; both exporters already handle either shape defensively, so nothing
is actually broken by leaving the prompt as-is. Left as a documented,
deliberately-not-fixed inconsistency rather than silently reverted with
no trace.

The `frame_output` test that claimed to check "no data loss" only checked `@graph` presence and
the root `@id` — tightened to actually diff `pyld.jsonld.expand()` output
between the raw and framed documents (real check: zero leaf values lost
across all 6 fixtures; the only differences are absolute type IRIs
re-compacted to CURIEs, which re-expand identically). `docs/CONFIGURATION.md`
gained the `validate_shacl_conformance` row it was missing.
`schemas/AGENTS.md` had one more stale "(not-yet-built)" claim about
`exporters/datacite.py` fixed in passing.

Two new Open Questions logged from this review, not resolved:
`schema:citation` is forbidden outright by the vendored SHACL shapes
(`cdifd:citationProperty`, `sh:maxCount 0`) despite Q2's mapping table
marking `citations` → `schema:citation[]` as **"Verified"** — a real
conflict between this repo's own decision and the artifact it's supposed
to implement (#19). `schema:url` appears in no agent's `fields:` list at
all, so the `url|distribution` required OR-group can currently only ever
be satisfied via `schema:distribution` from real generated output (#20).

Full verification green throughout: `ruff check` clean, `uv run python -m
mypy src/ scripts/` clean (0 errors), full `-m "not live"` suite, `-m
regression`, and the visor suite (via `uv run python -m pytest visor/tests
-p nicegui.testing.user_plugin -o asyncio_mode=auto -m "not live" -q`).

## Step 7 — Open Questions #16-#20 resolved (2026-09-04, post-Opus-validation-follow-up)

All five open questions the Step 5.5/Step 6/Opus-review passes surfaced but
deliberately left open are now resolved, in one combined pass (each with
its own commit(s)):

- **#16 (nested `schema:identifier` cardinality)** — singular
  `schema:identifier` (preferred match first, per `_SCHEME_ORDER`) plus
  `schema:sameAs` overflow for any additional match, at every nesting
  level `identifier_enricher.py` writes to. New shared
  `types.entity_identifiers()` (read: singular + overflow, preferred
  first) and `identifier_enricher._write_identifiers()` (write). Every
  exporter reading a nested `schema:identifier` (`dataverse.py`'s
  `_build_authors`, `datacite.py`'s `_identifier_entries`/
  `_preferred_identifier`, `croissant.py`'s `_first_identifier_url`) now
  goes through the shared reader. `doi_resolver.py`'s Crossref-backfilled
  placeholders (`"schema:identifier": []`) now omit the key entirely,
  consistent with "absent, not empty" (same convention as constraint C6's
  `schema:sameAs`). The top-level document's own `schema:identifier`
  (a genuinely list-valued property per the vendored schema's top-level
  `properties`, not its `$defs`) is untouched.
- **#17 (`schema:contributor`'s Role wrapper)** — restructured
  `config/agents.yaml`'s `creators_publishers` prompt (the only agent
  producing role-carrying `schema_contributor` entries — confirmed
  `media_files` never did, despite the original task brief's blast-radius
  guess) to the vendored `{"@type":["schema:Role"], "schema:roleName",
  "schema:contributor": <Person|Organization>}` shape. New shared
  `exporters/datacite.py::_role_and_actor()` helper splits a contributor
  entry into `(role, actor)`, handling both the Role wrapper and a bare
  (role-less) actor, used by `_build_resource`'s `_RESOURCE_ROLE_MAP` loop
  and `_build_creators`'s leftover-contributor fallback.
  `exporters/dataverse.py::_build_dataset_contact` updated the same way.
  Judgment call, flagged for reviewer double-check: the nested actor's own
  `@type` is hardcoded to `schema:Organization` (the prompt never asks the
  LLM to classify a contributor as Person vs. Organization the way it does
  for `schema_creator`) — a deliberate simplification, not a data loss (no
  Person-specific fields like `schema:givenName` existed on this shape
  before either).
- **#18 (`dcterms:conformsTo` missing the core URI)** — `_inject_envelope`
  now emits both `https://w3id.org/cdif/core/1.0` and
  `https://w3id.org/cdif/discovery/1.0` (core first) on
  `schema:subjectOf.dcterms:conformsTo`, matching `cdifd:
  metadataProfileProperty`'s two `sh:hasValue` constraints exactly.
  `tests/test_shacl_and_framing.py`'s hand-built `CONFORMANT_FIELDS`
  fixture already carried both URIs (built ahead of this fix, in Step 6);
  that test's real-golden-fixture assertion was retargeted from the
  now-fixed conformsTo violation to `resourceIdentifierProperty` (missing
  `@type` on the document's **top-level** `schema:identifier` entries, not
  the nested ones — corrected here on review; adding `@type` to only the
  top-level entries of a fixture clears the violation on its own — a real,
  still-open, separate gap; #16 only fixed cardinality, not `@type`
  tagging), which remains the one violation guaranteed across all 6
  fixtures.
- **#19 (`schema:citation` forbidden by SHACL)** — retargeted to
  `dcterms:bibliographicCitation` throughout: `CDIFDiscoveryOutputModel`
  (field renamed `schema_citation` → `dcterms_bibliographic_citation`),
  `config/agents.yaml`'s `rights_funding_citations` agent (`fields:` +
  prompt JSON examples — the field-name occurrences only, no other
  wording touched), `exporters/datacite.py::_build_citations`, all 6
  golden fixtures (mechanical key rename in place; only
  `sample_input03.json` carried real citation data, preserved verbatim).
  **Judgment call**: kept the existing structured per-citation shape
  (title/volume/issue/start_page/end_page/edition/conference_place/
  conference_date) rather than collapsing to a single formatted citation
  string — nothing in the vendored `schema.json`/`shacl.ttl` constrains
  this property's shape (it isn't a vendored first-class property at all,
  unlike `schema:citation` which was), and correctly formatting a
  citation string across highly variable inputs (journal article vs.
  conference paper vs. partial data) is a nontrivial judgment call of its
  own, independent of the rename. Flagged for a future pass if literal
  -text DCMI conformance for this field ever becomes a hard requirement.
- **#20 (`schema:url` unreachable from real output)** — `pipeline.py::
  _process_resource` now sets `schema:url` to `resource.url` immediately
  after `merger.merge()`, but only when no agent already produced a value
  (defensive — none currently do), only when `resource.url` is non-empty,
  **and only when it's an actual `http(s)://` URL** — `resource.url` can
  be a bare DOI for some input sources (`sample_input06.json`'s input is
  exactly this: `"url": "10.5880/gfz.4.1.2020.012"`), and writing that
  raw into `schema:url` pre-empted both `exporters/datacite.py` and
  `exporters/croissant.py`'s own, smarter DOI→`https://doi.org/...`
  resolution logic — a real regression caught on review and fixed by
  adding the scheme check; `sample_input06.json`'s fixture no longer
  carries a `schema:url` key (correctly — it has no real URL, only a DOI).
  This is deliberately the *input* URL the pipeline was given, not a
  separately-verified "documented landing page" — documented inline at
  the call site. **Correction on the stated rationale**: the "required
  floor's `url|distribution` OR-group" this fallback references is
  `CDIFDiscoveryOutputModel`'s Pydantic `model_validator`, which
  `validate_output()` exercises — but `validate_output()` is never called
  from `pipeline.py`/`merger.py`/`cli.py` in the live pipeline, only from
  tests and from `exporters/datacite.py` against the *DataCite* model. So
  this fallback's actual live effect today is on the two exporters (fixed
  above) and on `check_shacl_conformance`'s `accessProperty` shape (which
  does check `url|distribution` and does run when
  `validate_shacl_conformance` is enabled) — not on any runtime validation
  gate, since none currently exists. New `TestPipelineSchemaUrlFallback`
  in `tests/test_pipeline_integration.py` covers all three cases (fires,
  doesn't override, no-op when input has no URL either) — extended on
  review to also cover the bare-DOI case.

**Cache/fixture migration mechanics** (worth recording since it's easy to
get wrong on a future field rename): #17 and #19 both change either the
LLM-facing prompt text or an agent's field list, which changes the LLM
response disk-cache key (`cache.py:_make_key` hashes prompt +
response-model name, and a per-agent response model's name is itself a
digest of its field list — see `CDIFDiscoveryProfile.build_output_model`).
**Correction (found during the #21/#22/#23 round):** a field's *type
annotation* invalidates the cache too, independently of both — the
digest hashes each field's `repr(annotation)`, so widening
`dcterms_bibliographic_citation` from `list[dict[str, Any]]` to
`list[dict[str, Any] | str]` for #21 changed `rights_funding_citations`'s
digest with the prompt and field list both byte-identical. Same
migration recipe applies regardless of which of the three actually
changed.
Both changes therefore invalidated the committed
`tests/fixtures/golden/cache/` entries for the `creators_publishers` (#17)
and `rights_funding_citations` (#19) agents, across all 6 recorded inputs.
Rather than a live `make record-golden` re-recording (unnecessary — the
underlying facts extracted didn't change, only their key/shape), the
cache was migrated mechanically: the old cached response for each
affected (agent, resource) pair was read via the real `BaseAgent`/
`CacheManager` machinery (a guaranteed cache hit against the *pre-edit*
code), transformed in Python to the new shape (contributor Role-wrap /
citation key rename), and written back under the *post-edit* code's own
computed cache key (rebuilding the exact prompt text and, for
`creators_publishers`, remembering that its cache key also folds in
`tools=["lookup_organization"]` — a gap the first attempt at this missed
and had to redo). `tests/fixtures/golden/expected/*.json` were transformed
the same way (mechanical `json.load`/transform/`json.dumps`, no
re-recording) for all five fixes at once. Full `-m regression` suite
verified green after the migration, not just `-m "not live"`.

`ruff check src/ tests/ scripts/`, `uv run python -m mypy src/ scripts/`
(0 errors), the full `-m "not live"` suite, `-m regression`, and `uv run
python -m pytest visor/tests -p nicegui.testing.user_plugin -o
asyncio_mode=auto -m "not live" -q` are all green.

### Opus validation follow-up on #16-#20 (2026-09-04, same session)

An Opus review of the #16-#20 range found 4 more real bugs, all fixed the same session:

- **`schema:url` fallback (#20) accepted a bare DOI as a "URL"** — see #20's row above, now guarded with an `http(s)://` prefix check. `sample_input06.json`'s fixture no longer carries a `schema:url` key.
- **#17's Role-wrapper detection disagreed between exporters** — see #17's row above, now both key on `schema:contributor`/`schema:roleName` presence.
- **#16's "absent, not empty" rule was only implemented for `doi_resolver.py`'s backfill path** — `config/agents.yaml`'s prompts still instruct the LLM to emit `"schema:identifier": []` when nothing is found (unchanged, since editing that wording again would invalidate the LLM cache a second time for no real benefit), and nothing stripped that placeholder when enrichment didn't happen. New `_strip_empty_identifier()` in `identifier_enricher.py`, called at the end of every per-entity code path (creator, affiliation, personal creator, publisher, funder) regardless of whether that path wrote a real identifier — deletes the key only when it's still falsy (`[]`/`{}`), never touches a real value. `tests/fixtures/golden/expected/*.json` and 7 existing tests updated to assert the key is absent, not `[]`, on an unresolved entity.
- **`_enrich_affiliations`/`_enrich_publisher` silently dropped a second resolved identifier instead of overflowing it to `schema:sameAs`** — both used to build a single identifier dict directly via a now-removed `_preferred_identifier()` helper, bypassing the shared `_write_identifiers()`/`_identifier_entries()` pair that `_enrich_creators`/`_enrich_funding` already used correctly. Real data loss in committed output: `sample_input05.json`'s affiliation (`matched_via: "ror_affiliation+isni_sru"`) and publisher both had a real ISNI silently discarded, keeping only ROR. Both call sites now go through the shared writer; the fixture was corrected with real re-resolved values (network calls made, not fabricated — see the actual `schema:sameAs` entries added).

Also pruned 18 stale entries from `tests/fixtures/golden/cache/cache.db` (12 keys superseded by the #17/#19 prompt changes, never removed; 6 dead keys from the first, incomplete migration attempt) — verified by instrumented replay (wrapping `diskcache.Cache.get` to record every key actually requested across all 6 fixtures) that the remaining 30 keys are sufficient; `-m regression` re-confirmed green with dummy API keys (a silent live-call fallback would fail loudly, not pass). Added `*.db binary` to `.gitattributes` — `git show <rev>:path/to/cache.db` was silently corrupting the blob (line-ending normalization applied to a SQLite file) though real checkouts were unaffected.

Full verification green throughout: `ruff check`, `uv run python -m mypy src/ scripts/` (0 errors), `-m "not live"` (1225 passed), `-m regression` (7 passed), visor suite (186 passed).

### Opus analysis + fix round on #21-#23 (2026-09-04, same session)

An Opus agent was asked to analyze (not implement) Open Questions #21 and #22 and recommend concrete fixes, given both were left open by the prior round. Its recommendations (plain-literal citation string over a nested schema.org shape; bare `{"@id": ...}` sameAs overflow with reverse-parsing on read) were adopted as written and implemented directly, along with a new #23 (the top-level `schema:identifier` cardinality gap the same review surfaced) — see the #21/#22/#23 rows above for the resolutions themselves. Notable while implementing:

- The Opus review corrected a real gap in its own brief: DCMI's published term definition for `dcterms:bibliographicCitation` gives it `rdfs:range rdfs:Literal`, settling #21 in favor of a plain string outright — the "give the sub-keys real CURIE terms via a nested schema.org object" option floated when #21 was first logged would have been JSON-LD-real but RDF-wrong (a typed node under a literal-only property), not actually the better fix.
- Confirmed empirically (not assumed) that dropping provenance on `schema:sameAs` overflow entries (#22) loses nothing: every field on an overflow entry is sourced from the same single `IdentifierMatch` as the sibling primary `schema:identifier` entry, verified against all 4 real occurrences in the committed golden fixtures before this round (`sample_input04.json`/`sample_input05.json`) — `matched_via`/`confidence`/`status` were byte-for-byte identical between primary and overflow in every case.
- Fixing #22 surfaced a second, previously-unnoticed bug in the same area: `identifier_enricher.py::_SCHEME_URI["ISNI"]` built `https://isni.org/<id>` (no `/isni/` path segment), while `pid_validator.py::resolve_pid` and `isni_client.py` both already used ISNI's real canonical resolver form, `https://isni.org/isni/<id>` — one file disagreed with the rest of the codebase. Harmless before #22 (the identifier's real value lived in `schema:value` regardless of the URL), but #22's fix makes that URL the *only* surviving record for an overflow entry, so it had to be corrected in the same pass, not deferred.
- #21's fix required widening `CDIFDiscoveryOutputModel.dcterms_bibliographic_citation`'s annotation (`list[dict[str, Any]]` → `list[dict[str, Any] | str]`) so `validate_output()` accepts an already-formatted document — this changed `build_output_model`'s per-agent digest for `rights_funding_citations` (the digest hashes the annotation's `repr()`, not just the prompt text), invalidating that agent's 6 cached LLM responses across all fixtures even though the prompt itself never changed. Migrated mechanically: captured every `(prompt, response_model_name, key)` triple across a full regression replay before and after the edit, matched entries by identical prompt text, and copied each stale entry's already-cached value to its new digest-derived key — no data transform (the underlying LLM response didn't change, only the class name hashed into the key), no API key needed. This is a real correction to this doc's own "Cache/fixture migration mechanics" note (Step 7, below) — that note previously said only prompt text or an agent's field *list* invalidate the cache; a field's type annotation does too, independently of both.
- Fixed alongside, not part of #21/#22/#23 themselves: `exporters/datacite.py::_build_citations`'s filter only ever accepted a dict with a `"title"` key, silently dropping every citation once #21 made a plain string the real shape — relaxed to accept a non-empty string too (`DataCiteSchema46._normalize_citations` already handled a bare string correctly; only the filter upstream of it needed updating). `exporters/datacite.py::_build_alternate_identifiers` (the *document-level* `schema:sameAs` consumer, a different code path from #22's nested-entity fix) only read `schema:value`, silently dropping a bare `{"@id": ...}` overflow entry if #23's defensive top-level-overflow path is ever actually exercised (not yet reachable in practice, since `core_metadata`'s prompt only ever emits one identifier) — added an `@id` fallback for consistency, since it's the same shape mismatch class as #22, just one level up and currently dormant.

Full verification green throughout: `ruff check` (src/tests/scripts), `uv run python -m mypy src/ scripts/` (0 errors), `-m "not live"` (1246 passed, +21 new tests covering the citation formatter, the schema:identifier collapse, and `entity_identifiers()`'s reverse-parsing), `-m regression` (7 passed, cache-replay only — confirmed no live API calls needed despite the digest change), visor suite (186 passed).

## Step 5 — Structure fetcher: SKIPPED for v1 (see Backlog)

Decided: not building `enrichers/structure_fetcher.py` now. No consumer exists (`ResourceDescription` has no structure field, `agents/base.py::_build_resource_dict` hardcodes a strict 5-key dict, CDIF DataDescription itself is deferred per spec §2) — building it now would be dead code. Tracked in Backlog below so this doesn't get lost.

## Backlog — deferred, not forgotten

- **Structure fetcher (`enrichers/structure_fetcher.py`).** Explicitly deferred, not dropped. Build this when CDIF DataDescription work actually starts (spec §2/§7/§9). At that point also needs: `ResourceDescription` gaining a structure field, `agents/base.py::_build_resource_dict`'s strict 5-key `dict[str, str]` return type changed to carry it, `PipelineConfig.enable_structure_fetch`, a `Pipeline._maybe_fetch_structure()` step mirroring `_maybe_fetch_content()`, and — the part easy to get wrong — the "measured, never generated" invariant test must target LLM *output* (generated fields ⊆ measured columns) once there's a real prompt path, not just the fetcher's own input handling. Open Questions #10 (format list/sample strategy) and #11 (ordering vs. content-fetch) stay open until this is picked back up.
- **Croissant `recordSet` / CDIF DataStructure profile.** Blocked on the structure fetcher above (spec §3.4, §7). Correction (2026-09-04): earlier notes in this doc and `exporters/croissant.py`'s docstring called its absence "a gap" — per the real Croissant 1.1 spec, `recordSet` is simply optional; its absence is fully conformant, not a defect. Framing corrected here; still worth building once there's real column data to put in it, just not because leaving it out is wrong today.

- ~~Two real, additional shape mismatches surfaced by Step 5.5, deliberately not fixed — Open Questions #16 and #17.~~ **Resolved in Step 7** (nested `schema:identifier` cardinality, and `schema:contributor`'s Role wrapper) — see that section and the Open Questions table.
- ~~Neither `exporters/datacite.py` nor `exporters/croissant.py` is wired into anything yet.~~ **Resolved (2026-09-06): CLI only.** `gema process` gained a repeatable `--export {datacite,croissant}` option — after the primary CDIF output is written, each requested format is run (pure crosswalk, no LLM call) and written as a sibling file next to it (`<output>.datacite.json`/`<output>.croissant.json`), via a new `OutputWriter.resolve_output_path()` helper (factored out of `write()`'s own filename-derivation logic so the CLI doesn't duplicate it). `--export` requires `--output` (no sibling location exists for stdout mode). A single export failing — even one an exporter itself wasn't supposed to raise — is caught, reported as a warning, and never blocks or corrupts the primary output; this is enforced by `tests/test_cli.py::test_process_export_failure_does_not_block_primary_output`. **Still not wired into Visor's UI** — that remains open, tracked here, not done as part of this pass (deliberately excluded: a UI download/export affordance is a separate, heavier scope than a CLI flag).

## A/B diagnostic (spec §9, manual, not CI-gating)

- [x] `scripts/ab_eval_cdif_vs_datacite.py` using the Step 2 baseline snapshots (2026-09-06). Side A: current pipeline (`config/agents.yaml`) cache-replayed over the 6 golden inputs, crosswalked through `exporters/datacite.py::to_datacite_json`. Side B: NOT re-run — `tests/fixtures/golden_datacite46_baseline/expected/*.json` already *is* the frozen, once-recorded direct-DataCite-generation output, so the script just reads it (re-running `config/legacy/agents_datacite46.yaml` would need re-registering the deregistered `datacite-4.6` schema for zero added signal). Scored per-resource + per-field via `json_semantic_diff`, same as `test_regression.py`. `make ab-eval` to run; smoke-tested in `tests/test_ab_eval_script.py` (marked `regression`).
  - **Verified, not zero-network**: matches `test_regression.py`'s own guarantee exactly (LLM calls 100% cache-replayed, dummy provider keys enforce that) — but neither this script nor `test_regression.py` disables identifier enrichment/DOI resolution, and `identifier_enricher.py`/`doi_resolver.py`'s ROR/ISNI/ORCID/doi.org clients cache nothing, so both make real small GET requests to those public registries on every run. Pre-existing behavior, not introduced here — documented in the script's module docstring since the directive asked to verify this explicitly.
  - **Read scores as informational, not a gate**: the baseline predates all of Open Questions #16-#23 (identifier cardinality, contributor Role wrapper, citation-shape collapse, `schema:url` fallback, ...) — real, intentional CDIF-side shape changes made after the snapshot was frozen, unrelated to the crosswalk's correctness. A live run today (2026-09-06) shows all 6 resources well below the 0.85 threshold (0.00-0.32 overall) for exactly this reason — e.g. `dcterms:bibliographicCitation`'s post-#21 literal-string shape will never match the baseline's pre-#19 structured `schema:citation` dict, by design. Per-field scores still confirm no field went silently empty (e.g. `creators`/`titles`/`rights` all populated on both sides even when their content legitimately differs) — that spot-check is this tool's real day-to-day value, not the overall number.
- [x] Pass over `scripts/eval_common.py`, `run_live_eval.py`, `validate_real_output.py`, `reverse_input.py`, `generate_ground_truth_schema.py`, `tests/fixtures/do_catalog/ground_truth*` (2026-09-06). Found two genuinely different situations, not one uniform "all stale":
  - **Actually broken** (`SCHEMA_NAME`/`-s`/`--schema` default of `"datacite-4.6"`, deregistered): `eval_common.py::run_pipeline_for_model` and `run_live_eval.py` (`make live-eval`'s entry point) both called `get_registry().get("datacite-4.6")` and would fail outright on first use. Fixed: `run_live_eval.py`'s `-s/--schema` default is now `cdif-discovery` (it scores the live pipeline's real CDIF output against `tests/fixtures/golden/expected/`, which is already CDIF-shaped — no other change needed there). `eval_common.py::run_pipeline_for_model` now runs the real (CDIF) pipeline and crosswalks the result through `exporters.datacite.to_datacite_json` (pure, no LLM call) before returning — its `extract_*`/`compare_outputs` helpers read DataCite field names and are meant to score against the deliberately-DataCite-shaped do_catalog ground truth (see below), so the crosswalk is what makes them correct again rather than what breaks them. Verified directly (no live API call, real key in this environment turned out to be invalid — 401 — so left as a follow-up for whoever runs the live checks next): built a `MetadataDocument` from a real committed CDIF golden fixture and confirmed `to_datacite_json(...)` round-trips through every `extract_*` helper correctly (creator names, ROR ids, subjects, geo places all populated). `SCORING_PROMPT`/`GEval`'s criteria text hardcoded "DataCite 4.6 metadata" — genericized to cover both callers, since `run_live_eval.py`'s candidate is CDIF JSON-LD, not DataCite.
  - **Not actually stale, by design**: `reverse_input.py` and `generate_ground_truth_schema.py` both operate exclusively on `tests/fixtures/do_catalog/ground_truth*` (confirmed via `generate_inputs.py`'s own `--ground-truth-dir` usage and `validate_ground_truth.py`'s `REQUIRED_KEYS`), which is a hand-curated, deliberately-DataCite-shaped corpus (not regenerated by the pipeline) — `generate_ground_truth_schema.py` dumps `DataCiteOutputModel`'s JSON schema (still directly importable post-deregistration) for hand-editing that corpus, and ran clean unchanged. Left untouched; noting this explicitly so it doesn't get re-flagged as stale next pass.
  - `validate_real_output.py` (the "would a human reviewer accept this record" live-output gate, no ground truth involved) was rewritten to check the real CDIF field names directly (`schema:name`, `schema:creator`'s `@list`, `schema:description`, `schema:keywords`/`schema:about`, `schema:datePublished`/`dateCreated`) rather than DataCite names or a crosswalk — this script validates the actual generation target as it ships, not an export artifact, so crosswalking would have hidden real CDIF-shape defects instead of catching them. `pid_validator.py`'s `validate_pids()` needed no change — already CDIF-native from the Step 2c blast-radius retarget.
  - Full verification: `ruff check src/ tests/ scripts/`, `uv run python -m mypy src/ scripts/` (0 errors), `uv run python -m pytest -m "not live"` (1246 passed, 1 skipped, 17 deselected — unchanged).

## Open questions log

| # | Question | Status |
|---|----------|--------|
| 1 | CDIF vendored artifact repo + commit SHA | **resolved**: `doc-corediscovery`@`81c28260778426cc61302105fc7191b4db360bc9` |
| 2 | CDIF Discovery field coverage beyond required floor | **resolved**: full verified per-field mapping (32 properties), see "Q2" section |
| 3 | `extra="forbid"` vs `"allow"` on output_model | **resolved**: `extra="allow"` + a `model_validator` hard-enforcing the required floor and the two conditional (anyOf) groups (license/conditionsOfAccess, url/distribution) |
| 4 | JSON-LD envelope emission site | **resolved**: inside `merge_agent_results` |
| 5 | SHACL/JSON-LD framing execute in v1? | **resolved**: yes — `pyshacl`, `rdflib`, `pyld` added as new runtime deps |
| 6 | Enrichment architecture fork | **resolved: option (A)** |
| 7 | Golden fixture strategy | **resolved**: full replace + baseline snapshot |
| 8 | DataCite export LLM-call scope | **resolved: none, pure crosswalk** |
| 9 | Croissant top-level field mapping | **resolved**: verified against `docs/croissant-spec-1.1.md`@`0e5dcb796dba285b396011638a68909c78a39664` — corrected `distribution` from "Croissant-specific" to required, see Q9/Step 4 |
| 10 | Structure fetcher format list / sample strategy | deferred with the whole feature — see Backlog |
| 11 | Content-fetch vs. structure-fetch ordering | deferred with the whole feature — see Backlog |
| 12 | Does structure-fetcher ship in v1 at all | **resolved: no** — see Backlog, must stay visible |
| 13 | Where DataCite vocab/affiliation table lives post-rewrite | **resolved** (duplicate of Step 2's own resolution note, never reflected here): stays in `config/agents.yaml`'s CDIF-facing prompts — SPDX/CC license priority, ANID/FONDECYT funding taxonomy, and the Chilean ministry hierarchy table are domain knowledge for reading Spanish source text, not DataCite-shape knowledge, so nothing to move to `exporters/datacite.py` |
| 14 | `visor/session_settings.py` override migration | **resolved**: checked, not actually a gap — `visor/settings.py::apply_agent_overrides` already skips (never raises on) an override whose agent ID or provider no longer exists, by design. Agent IDs/providers didn't change in the pivot, so pre-pivot persisted overrides keep working unchanged |
| 15 | `config/migrate.py` hardcoded schema name | **resolved**: keep, add warning |
| 16 | Nested `schema:identifier` cardinality: vendored schema wants singular on Person/Organization/MonetaryGrant, gema always builds a list | **resolved**: singular `schema:identifier` (first/preferred match, `_SCHEME_ORDER`) plus `schema:sameAs` overflow for any additional match, on every entity `identifier_enricher.py` writes to (creator, affiliation, publisher, funder — `schema:contributor`'s nested actor carries no identifier in practice, so untouched). New shared `types.entity_identifiers()` reader (merges singular + overflow, preferred first) used by `dataverse.py`/`datacite.py`/`croissant.py`; `doi_resolver.py`'s Crossref-backfilled placeholders now omit the key entirely instead of `[]`. **Correction (found on the #21/#22 Opus review round):** this row's original text claimed the *document's own* top-level `schema:identifier` was "untouched... per the vendored schema's own top-level `properties`, not `$defs`" — that was wrong. `schema.json`'s `properties.schema:identifier` is `anyOf: [Identifier, string]`, singular, exactly like the nested `$defs` — the same cardinality gap, one level up, simply not noticed at the time. Now tracked and fixed as Open Question #23. |
| 17 | `schema:contributor`'s Role wrapper: vendored schema wants `{"@type":["schema:Role"], "schema:roleName", "schema:contributor": <actor>}`, gema reads/writes a flat `{"schema:name","role","schema:email"}` | **resolved**: restructured to the vendored shape exactly — `config/agents.yaml`'s `creators_publishers` prompt (the only agent that produces role-carrying `schema_contributor` entries; `media_files` never did), `exporters/dataverse.py::_build_dataset_contact`, `exporters/datacite.py` (`_RESOURCE_ROLE_MAP` loop and the leftover-contributor-becomes-creator fallback, via a new shared `_role_and_actor()` helper). **Bug fixed on review**: `_role_and_actor` originally gated detection on `@type == ["schema:Role"]` exactly, while `dataverse.py`'s own detection (written first, in the same range) keyed on `schema:roleName` presence with no `@type` check — the two exporters disagreed on the same input, and an entry with a correct Role wrapper but a missing/wrong `@type` (a realistic LLM slip) silently vanished from DataCite output entirely, with no warning. Both now key on `schema:contributor`/`schema:roleName` key presence, matching each other. The nested actor's own `@type` still defaults to `schema:Organization` (the prompt doesn't ask the LLM to classify a contributor as Person vs Organization the way it does for `schema_creator`) — checked against every consumer, nothing branches on Person vs Organization for a contributor today, so this produces a wrong `@type` in published JSON-LD but no functional corruption; still a deliberate simplification worth revisiting if a contributor-role consumer ever does branch on actor type. A bare role-less contributor entry (still valid per the vendored `anyOf`) is untouched. |
| 18 | `dcterms:conformsTo` on `schema:subjectOf`: the vendored shapes' `cdifd:metadataProfileProperty` requires *both* `https://w3id.org/cdif/core/1.0` and `.../cdif/discovery/1.0`, but `CDIFDiscoveryProfile._inject_envelope` only emits the discovery URI — every real golden fixture fails this SHACL check for exactly this reason | **resolved**: `_inject_envelope` now emits both URIs (core first, then discovery, matching `tests/test_shacl_and_framing.py`'s existing conformant fixture). Both are known-dead as of the vendored SHA's date (2026-09-04, CDIF has no tagged releases) — same status, not a new gema-introduced gap. |
| 19 | `schema:citation` is forbidden outright by the vendored shapes (`shacl.ttl`'s `cdifd:citationProperty`: `sh:maxCount 0`, "not recommended... because of semantic ambiguity. Use dcterms:bibliographicCitation... or schema:relatedLink") — but the Q2 mapping table (line ~70) maps `citations` → `schema:citation[]` and marks it **"Verified"**. A real conflict between this repo's own field-mapping decision and the vendored artifact it's supposed to implement, found by Step 6's SHACL check (`sample_input03.json` fails `citationProperty` for exactly this reason) | **resolved**: retargeted to `dcterms:bibliographicCitation` — `CDIFDiscoveryOutputModel.dcterms_bibliographic_citation` (was `schema_citation`), `config/agents.yaml`'s `rights_funding_citations` agent (`fields:` + prompt, including JSON examples), `exporters/datacite.py::_build_citations`, all 6 golden fixtures (mechanical key rename; only `sample_input03.json` had non-empty data). The shape was initially kept structured (the same title/volume/issue/pages/edition/conference dict) rather than collapsed to a formatted string — that follow-on shape question was tracked separately as Open Question #21 and has since been resolved there (collapsed to a literal string); see that row. |
| 20 | `schema:url` appears in no agent's `fields:` list in `config/agents.yaml` and nothing in `src/` writes it at the top level — the `url\|distribution` required OR-group can currently only be satisfied via `schema:distribution`, never via `schema:url`, even though the field exists on `CDIFDiscoveryOutputModel` and `exporters/datacite.py`/`exporters/croissant.py` both read it. `ResourceDescription.url` (always present on input) could satisfy this for free via `_inject_envelope`, but that changes what "the resource has a URL" means (input URL vs. a documented landing page) — a real design decision, not made here | **resolved**: `pipeline.py::_process_resource` sets `schema:url` to `resource.url` right after `merger.merge()`, but only when no agent already produced one (defensive — no agent currently does), only when `resource.url` is non-empty, **and only when it's a real `http(s)://` URL** (a bug fixed on review: `resource.url` can be a bare DOI for some input sources — `sample_input06.json` is exactly this — and writing that raw pre-empted both exporters' own smarter DOI-to-URL resolution). Deliberately the *input* URL, not a separately-verified "documented landing page" — documented inline at the call site. Placed in `pipeline.py`, not `CDIFDiscoveryProfile.merge_agent_results`/`_inject_envelope`, since the `Schema` Protocol has no access to `ResourceDescription`. |
| 21 | `dcterms:bibliographicCitation`'s kept-structured shape (Q19's resolution) loses 100% of its data under real JSON-LD processing: its sub-keys (`title`, `volume`, `start_page`, ...) have no `@context` term, so `pyld.jsonld.expand()` produces `{"http://purl.org/dc/terms/bibliographicCitation": [{}]}` — every field dropped, pointing an `rdfs:Literal`-range DCMI term at an empty blank node. Not a regression (`schema:citation` had the identical defect before the rename), but Q19 explicitly re-examined this shape and its "nothing constrains this" justification addresses the vendored-artifact constraint, not the JSON-LD-processing one that actually bites | **resolved**: collapsed to a plain literal string, rendered deterministically in code (`CDIFDiscoveryProfile._format_bibliographic_citation`, called from `merge_agent_results`), not by the LLM — the DCMI term definition itself gives `dcterms:bibliographicCitation` `rdfs:range rdfs:Literal` (and makes it a sub-property of `dcterms:identifier`), so a structured object was never the "correct" shape regardless of the JSON-LD-expansion bug; a nested `schema:isPartOf`/`PublicationVolume`/`PublicationIssue` breakdown (real schema.org vocabulary, no new `@context` terms needed) was considered and rejected for v1 as extra work with no current consumer (only `exporters/datacite.py`'s own gema-invented `citations` extension field reads this at all) — left as a documented, cheap future follow-up, not a new open question. `config/agents.yaml`'s prompt is unchanged (the LLM still emits the structured dict; it's an easier extraction task) — the field's Pydantic annotation widened from `list[dict[str, Any]]` to `list[dict[str, Any] \| str]` purely so `validate_output()` accepts an already-formatted document too. That annotation widening still changed `build_output_model`'s per-agent digest for `rights_funding_citations` (the digest hashes the annotation's `repr()`, not just the prompt), invalidating its 6 cached LLM responses — migrated mechanically (re-keyed under the new digest, no data transform since the underlying cached dict didn't change, no API key needed), the same class of cache-key migration used for #17/#19. Golden fixtures: only `sample_input03.json` had real citation data; its expected output now carries the formatted string in place of the structured dict. |
| 22 | `schema:sameAs` on a nested Person/Organization (the #16 overflow slot) is off-spec: the vendored `$defs/Person`/`$defs/Organization` type it as `anyOf: [string, {object with @id}]` — pointedly not `$ref: "#/$defs/Identifier"`, unlike the *dataset-level* `schema:sameAs`, which does reference `Identifier`. Writing a full `{schema:propertyID, schema:value, schema:url}` PropertyValue there (what `_write_identifiers` does today) validates only by accident (the `{@id}` branch has no `required`/`additionalProperties:false`) and expands to a blank node under a property the spec means to hold a plain IRI/string | **resolved**: overflow entries are now written as a bare `{"@id": <resolvable URL>}` reference (`identifier_enricher.py::_write_identifiers`) — provenance (`matched_via`/`confidence`/`status`) is dropped for these entries, not relocated, since every field in an overflow entry comes from the same `IdentifierMatch` as the sibling primary `schema:identifier` slot, which keeps it in full; nothing is actually lost. `types.entity_identifiers()` (the shared reader every exporter goes through) reverse-parses the scheme back out of the URL's host (`ror.org`/`isni.org`/`orcid.org`) so callers (`exporters/datacite.py`'s `name_identifiers`/`funder_identifiers`, the only real overflow consumer) still get the `propertyID`+`value` shape they want; an unrecognized host degrades to `{"schema:url": url}` rather than dropping the entry, and a pre-#22 full-PropertyValue-shaped `schema:sameAs` entry (legacy/hand-built) is still accepted unchanged. Found and fixed alongside this: `identifier_enricher.py`'s own `_SCHEME_URI["ISNI"]` built `https://isni.org/<id>` (missing the `/isni/` path segment `pid_validator.py`/`isni_client.py` both already use as ISNI's real canonical resolver URL) — cosmetic before this fix (the identifier's `schema:value` carried the real ID regardless), but load-bearing now that the URL is the *only* surviving record for an overflow entry; corrected, with the 5 affected ISNI URLs in `sample_input04.json`/`sample_input05.json` fixed to match. |
| 23 | Document-level `schema:identifier` has the same singular-vs-list cardinality gap as #16, one level up — the vendored `schema.json`'s `properties.schema:identifier` is `anyOf: [Identifier, string]`, singular, not the list `config/agents.yaml`'s `core_metadata` prompt (and every agent-produced/merged document) actually builds. Not noticed when #16 was resolved (that row's write-up incorrectly claimed this field was "untouched... per the vendored schema's own top-level `properties`, not `$defs`" — the opposite of what `schema.json` actually says); found on the #21/#22 Opus review round | **resolved**: same pattern as #16, one level up. `CDIFDiscoveryProfile.merge_agent_results` collapses the (normally one-entry, per the `core_metadata` prompt's own "UNA entrada" instruction) agent-produced list to a singular dict, overflowing anything beyond the first into `schema:sameAs` as a bare `{"@id": ...}` reference (#22's shape) — defensive, since the prompt already guarantees one entry today; omits the key entirely when empty ("absent, not empty", same convention as #16). `CDIFDiscoveryOutputModel.schema_identifier`'s own annotation is left unchanged (`list[dict[str, Any]]`, zero cache impact) — a new `mode="before"` field_validator wraps a singular dict back into a one-element list purely so `validate_output()` still validates a fully-merged document. Downstream consumers of the top-level field updated to read the singular shape (with defensive list-tolerance kept, for hand-built fixtures): `doi_resolver.py::_doi_identifier`, `exporters/dataverse.py` (`_build_title` fallback, `_build_alternative_url`), `output.py`'s DOI-derived filename logic. `exporters/datacite.py`/`exporters/croissant.py` needed no changes — both already read this field through a local `_as_list()` helper that treats a bare dict and a list uniformly. Golden fixtures: all 6 had exactly one entry; each now stores it as a singular dict (`sample_input02.json`, whose entry was empty, now omits the key entirely). |

## Post-PR#45 investigation: live-eval quality gate + content-fetch upgrade (2026-09-06)

PR #45 (this branch → `dev`) opened with the pivot complete but the live-eval quality gate failing (0.650 mean vs. 0.75 threshold, `reports/live_eval_20260906_122159.md`). An Opus agent was asked to plan (not implement) two follow-on features: (A) using CODATA's `semantic-croissant`/`croissant-live` MCP tooling — or parts of it, vendored locally, never the hosted server, same philosophy as vendoring CDIF's own artifacts — to upgrade content-fetch from flat-text to markdown, and (B) fixing the live-eval prompt-quality gap. Analysis only, no code changed by this pass. Full detail lives in that agent's transcript; headline findings and the resulting plan:

**Findings that reframe the whole problem — this is not (only) a prompt-quality issue:**
- **B-1**: `schema:dateModified` is generated by no agent — it's injected in `cdif_discovery.py`'s `_inject_envelope` as `datetime.now(UTC).date()`, i.e. "today". Every golden fixture is stamped `2026-09-04`; the eval ran `2026-09-06`. It fails on 6/6 fixtures by construction and will fail forever. Not a model or prompt problem — a harness defect.
- **B-2**: the gate has never passed. A pre-pivot report (`reports/live_eval_20260810_222935.md`, DataCite generation, different model, different judge) also scored 0.667 and FAILed. The 0.650 seen post-pivot is not a regression.
- **B-3**: the reference is circular — `make record-golden` snapshots the same model's own output, so live-eval partly measures run-to-run self-consistency (no `seed` on the `opencode` provider), not ground-truth accuracy. Concrete proof: `sample_input05`'s golden publisher doesn't match its own input's declared publisher; the live run matched the *input* and was scored down for it.
- GEval (the actual gate metric) only emits values in ~0.1 steps across the 6 runs (all exactly 0.600 or 0.700) — too coarse to treat 0.75 as a real pass/fail line yet.
- Field ownership confirmed against the real prompts (not guessed): `creators_publishers` owns creator/publisher/contributor, `rights_funding_citations` owns copyrightHolder/license/funding, `classification` owns keywords/about/audience, `core_metadata` owns additionalType. The creator/publisher fallback rule in the prompt runs creator→publisher (not the reverse assumed earlier); the real fix is a **deterministic code fallback** (publisher → creator → copyrightHolder cascade in `pipeline.py`, mirroring Open Question #20's `schema:url` fallback precedent) for the empty-actor cases, not a prompt rewrite.
- Content-fetch is genuinely coupled to Feature A: 5/6 golden inputs pre-bake inconsistent `fetched_content` (one is raw unstripped HTML, others are 3.5x the fetcher's own truncation limit) that never went through the real fetcher — so a markdown upgrade can't be evaluated until the corpus is re-baked from one consistent fetcher run, which is itself a re-record cycle. **Feature A is sequenced after Feature B**, not parallel, to avoid two re-record cycles fighting each other.
- CODATA's actual MCP-server source could not be verified (no internet access in that pass) — recommended NOT to adopt its JSON-LD/Croissant template generation (would duplicate gema's own native CDIF generation + already-built Croissant exporter, and risks violating the "structure is measured, never generated" invariant); the markdown-conversion idea is worth a cheap bake-off against off-the-shelf libraries (`trafilatura`, `markdownify`, `html2text`) before assuming CODATA's code itself is even usable (license/language/existence all unverified).

**Proposed phased plan** (not started — pending owner decisions below):
- **Phase B0** (no API cost, no re-record): strip/ignore `schema:dateModified` in the scorers; fix or override `sample_input05`'s golden publisher; record the pre-pivot 0.667 baseline here for context; re-run `make live-eval` to get the real starting number.
- **Phase B1** (code fallbacks only, zero cache/prompt impact): `resource.publisher` → `schema:publisher` → `schema:creator` → `schema:copyrightHolder` cascade in `pipeline.py`, plus the existing "Datos Abiertos del Estado de Chile → Estado de Chile" copyrightHolder rule made deterministic. Golden fixtures updated mechanically (deterministic transform), no live re-recording needed.
- **Phase B2**: branch on the concurrent model-swap experiment's result (see below) — ship a better model outright if it clears the gate; combine with prompt edits in one batch if it only partially helps; treat the metric itself as the constraint (pursue Open Question O-2) if no model or schema has ever cleared 0.75.
- **Phase B3** (one batch, one `make record-golden`): concrete prompt edits for `classification`'s English/non-Chilean bail-out gate (this is what collapsed 4 fields at once on `sample_input06`), `core_metadata`'s `additionalType` (currently zero positive few-shot examples despite being populated in 5/6 golden fixtures), and `classification`'s keyword faceted-form/geographic-qualifier rule.
- **Phase A** (content-fetch → markdown): source-check CODATA's actual repo/license/stack first; cheap bake-off against off-the-shelf libraries before vendoring anything; gate behind a new `content_format: "text"|"markdown"` config field, keeping the existing `clean_html_to_text` path and its 11-test contract untouched; re-bake the golden corpus's `fetched_content` from one consistent fetcher run only after Phase B lands.

**Open questions for the repo owner, not yet decided:**

| # | Question |
|---|----------|
| O-1 | Should `schema:dateModified` stay "today" (processing timestamp), or should `core_metadata` extract the resource's real last-updated date when present, falling back to today? |
| O-2 | Is 0.75 on GEval a real, calibrated quality bar, or should the gate switch to the already-computed per-field mean (finer resolution, already discarded today) and be recalibrated? |
| O-3 | Should `schema:audience`'s `mediator`/`education_level`/`instructional_method` sub-fields be scored at all, given they're drawn from a large cross-product no single golden answer can representatively cover? |
| O-4 | For the B1 publisher fallback: normalize `resource.publisher` (strip trailing `"(Chile)"`/`" - Gobierno de Chile"`) before copying it into `schema:creator`/`schema:copyrightHolder`, or copy verbatim? Verbatim reintroduces a suffix the system prompt explicitly forbids elsewhere. |
| O-5 | Is `sample_input05`'s golden publisher a fixture bug to fix, or a deliberate canonicalization gema should learn to reproduce? |
| O-6 | Given AGPL-3.0-only and gema's dependency-light posture, is vendoring CODATA's code on the table at all if a maintained PyPI library already covers the same need? |

A model-swap experiment (`scripts/compare_models.py`/`judge_models.py` against `tests/fixtures/do_catalog/`, candidates: `deepseek-v4-pro`, `glm-5.3`, `gpt-5.6-luna`, `longcat-2.0`, `omen-alpha` vs. the current `deepseek-v4-flash` baseline) was running concurrently with this analysis — see this doc's next changelog entry once it lands for the result and Phase B2's actual branch.

## Model-swap experiment (2026-09-06) — incomplete, blocked on opencode account credits

Ran `scripts/compare_models.py`/`judge_models.py` (both fixed for the CDIF pivot earlier this session, see the eval-tooling fix above) against the real 18-item `tests/fixtures/do_catalog/` corpus, to inform Phase B2 above. **Scope correction mid-run**: the user authorized testing only `gpt-5.6-luna`, `longcat-2.0`, `omen-alpha` against the `deepseek-v4-flash` baseline (the models they'd personally tried) — `deepseek-v4-pro` and `glm-5.3` were an unauthorized addition, stopped once flagged. Reporting the actual damage plainly, not minimizing it: both had already **fully completed** their 6-item screening runs before the correction landed and the process was killed — `deepseek-v4-pro` in ~161s wall-clock (6 real pipeline runs, ~5 agent calls each), `glm-5.3` in ~2775s (~46 min) wall-clock for the same 6 items, real API cost on both, no further use made of either past this screening data.

**Screening (`--limit 6`, structural score) — all 6 candidates + baseline:**

| Model | Avg overall | Status |
|---|---|---|
| `deepseek-v4-flash` (baseline) | 0.367 | authorized |
| `deepseek-v4-pro` | 0.373 | **unauthorized — informational only, excluded from the decision below** |
| `glm-5.3` | 0.433 | **unauthorized — informational only, excluded from the decision below** |
| `gpt-5.6-luna` | — | authorized, **0/6 succeeded** — real `Error code: 500 Internal Server Error` from opencode on every item (~80s per failed attempt); provider-side outage/instability for this model, not a code or config issue. Disqualified, not scored. |
| `longcat-2.0` | 0.408 | authorized |
| `omen-alpha` | 0.412 | authorized |

**Full 18-item run** (authorized candidates only — `gpt-5.6-luna` excluded per the failure above; the 6 already-screened items reused via `--rescore-only`, zero extra cost, only the remaining 12 items per model cost real calls):

| Model | Avg overall (structural, 18 items) | Judge (GEval, glm-5.3 as judge) |
|---|---|---|
| `deepseek-v4-flash` (baseline) | 0.471 | 0.456 |
| `longcat-2.0` | 0.481 | **not obtained — see below** |
| `omen-alpha` | 0.507 | **not obtained — see below** |

**Judge correlation — completed after a credit top-up.** `judge_models.py` (judge model `glm-5.3`, its established role from `run_live_eval.py`, not a generation candidate) first scored `deepseek-v4-flash`'s 18 items cleanly, then hit `openai.AuthenticationError: 401 — CreditsError: Insufficient balance` partway into `longcat-2.0`'s batch. This likely also explains an earlier, seemingly unrelated "401 invalid/expired key" finding reported by a different agent this session (`eval_common.py` fix commit) — same root cause (balance, not the key itself), misdiagnosed at the time. Once the opencode account's rolling quota reset, the remaining judge pass (`longcat-2.0` + `omen-alpha`) completed cleanly, both 0 GEval failures across 18/18 items.

**Final ranking, all 3 authorized models, both metrics:**

| Model | Structural (18 items) | Judge GEval (18 items) | Structural↔Judge Spearman ρ |
|---|---|---|---|
| `deepseek-v4-flash` (baseline) | 0.471 | 0.456 | — |
| `longcat-2.0` | 0.481 | 0.467 | 0.740 |
| `omen-alpha` | **0.507** | **0.489** | 0.682 |

**Final recommendation (at the time): switch the production model to `omen-alpha`.** It leads on both independent scoring methods (structural Jaccard-vs-truth *and* LLM-judge GEval), not just one — a consistent signal, not noise from a single metric — and both candidates' structural↔judge correlation is reasonably strong (ρ 0.68–0.74), so the two scoring methods aren't disagreeing about which model is better. The real cost is latency: baseline processed most items in single-digit seconds (warm-path) to ~30–80s (cold), while `omen-alpha`/`longcat-2.0` took 90–400+s *per item*, some single items exceeding 5–8 minutes. That's a real tradeoff for a batch pipeline with no interactive latency requirement (per `pipeline.py`'s own design — resources are processed independently, a single slow resource doesn't block others), so the quality gain would likely have been worth it here; it would not be if gema ever grows an interactive/synchronous use path.

**Phase B2 decision (2026-09-06): declined, staying on `deepseek-v4-flash`.** Explicit owner call, overriding the measurement-based recommendation above: `deepseek-v4-flash` remains the production default regardless of `omen-alpha`'s measured lead, per prior explicit instruction ("deepseek will continue to be the default, I just want gema to be able to work with all the models"). The benchmark numbers above stand as-recorded for future reference — nothing here is being re-measured or reversed, just not acted on. Phase B2 is closed on this basis: no model swap, proceed straight to Phase B3's prompt-edit batch against the `deepseek-v4-flash` baseline.

**Not investigated this round, flagged for whoever picks this back up**: whether `longcat-2.0`/`omen-alpha`'s slowness is model latency, a routing/queueing issue on opencode's side, or retries from transient errors (`omen-alpha` did hit a couple of retried 400s on `rights_funding_citations` mid-run, absorbed by the pipeline's existing retry logic) — not distinguished here.

## Eval tooling: judge/candidate quota separation + config/eval.yaml (2026-09-06)

Root cause found for the account lockout during the model-swap experiment above: `run_live_eval.py`'s judge client silently inherited `config/agents.yaml`'s `default_provider` (`opencode`) instead of a separate account, so judging a candidate model competed for the exact same rolling quota the candidate itself was consuming — `eval_common.py` already had the right idea (`DEFAULT_PROVIDER = "zai-coding-plan"`, and `judge_models.py`'s own docstring example always showed a `zai-coding-plan` judge), `run_live_eval.py` was just the outlier that never adopted it.

Fixed: `run_live_eval.py`'s judge argument is now `--judge` (was `--model`), taking a `provider:model` spec string via the existing `eval_common.parse_model_spec()` — same format `compare_models.py --models` and `judge_models.py --judge` already used, just applied consistently everywhere now. Default is `zai-coding-plan:glm-5.3`, resolved independently of production's `default_provider`, so a judge run can no longer cannibalize whatever account a candidate model is being tested against (or vice versa). `judge_models.py`'s duplicate `_find_provider` helper moved to `eval_common.find_provider()`, shared by both scripts.

Also added `config/eval.yaml` (new, dev-tooling-only — never read by `src/metadata_enricher`, production pipeline unaffected): judge spec, PASS/FAIL threshold, default candidate list, and named corpus path presets (`do_catalog`, `golden`) that `run_live_eval.py`, `compare_models.py`, and `judge_models.py` all now read as defaults — every corresponding CLI flag still overrides when passed, so passing a different corpus/model/judge on the command line keeps working exactly as before. This replaces several previously-`required=True` CLI flags (`--ground-truth-dir`, `--inputs-dir`, `--models`, `--judge`) with config-file-backed defaults, shrinking the common-case invocation to zero flags for the two corpora this repo actually uses.

Verified: `ruff check src/ tests/ scripts/ visor/` clean, `mypy src/ scripts/` + `mypy visor --exclude visor/tests` both 0 errors, full `-m "not live"` suite 1254 passed (unchanged) + `--help` smoke-checked on all 3 scripts to confirm config-file defaults resolve without error.

## Phase B1: deterministic actor fallback cascade (2026-09-06)

Implemented the Opus plan's Phase B1 (Post-PR#45 investigation section above) while opencode's rolling quota was rate-limited — zero live calls needed, pure code + mechanical fixture updates, same class of fix as Open Question #20's `schema:url` fallback.

`pipeline.py::_process_resource`, right after the `schema:url` fallback: a deterministic cascade fires only on genuinely-empty slots, never overriding a real agent-produced value —
1. `resource.publisher` → `schema:publisher`, when no agent produced one. Normalizes two known trailing-suffix forms first (`" - Gobierno de Chile"`, `" (Chile)"`) so the fallback doesn't reintroduce exactly what the shared system prompt already forbids agents from including (Open Question O-4's default resolution — narrow, documented, easy to extend if more forms turn up).
2. `schema:publisher` → `schema:creator`, when creator is empty (`schema:creator` is always `{"@list": [...]}`-wrapped by this point in the method; unwrapped via `types.jsonld_list_unwrap()` to check).
3. `schema:publisher` → `schema:copyrightHolder`, when empty (`schema:copyrightHolder` is a plain string field, unlike the other two).
4. `"Datos Abiertos del Estado de Chile"` license entry → `schema:copyrightHolder: "Estado de Chile"`, mirroring the `rights_funding_citations` prompt's own PRIORIDAD 3 rule (`config/agents.yaml`) made deterministic, checked only if steps 1-3 left the slot empty.

**Found while implementing, not assumed**: 4 of the 6 committed golden fixtures (`sample_input02`, `03`, `05`, `06`) already had `schema:copyrightHolder: ""` despite a fully-populated `schema:publisher` — i.e. this exact gap was already sitting in the cache-replayed regression suite, not just a live-only symptom. Updated those 4 `expected/*.json` files mechanically (copyrightHolder set to the publisher's own `schema:name`) — no cache-key impact (this fallback isn't part of any agent's LLM response or `build_output_model`'s digest, same as #20), no live re-recording needed. `sample_input01`/`04` already had a non-empty `schema:copyrightHolder` and are untouched, matching the never-override guarantee.

Tests: new `TestPipelineActorFallbacks` in `tests/test_pipeline_integration.py` (6 tests) — fires-and-cascades, both suffix-normalization forms, doesn't-override for an agent-produced publisher, doesn't-override for agent-produced creator/copyrightHolder, the license-based rule, and the no-fallback-fires case.

Verified: `ruff check src/ tests/ scripts/ visor/` clean, `mypy src/ scripts/` 0 errors, `-m regression` 10 passed (cache-replay confirms the updated fixtures match the new fallback behavior exactly), full `-m "not live"` suite 1260 passed (+6 new).

**Not done in this pass** (still blocked on opencode's quota, tracked together): B0's final "re-run `make live-eval` to see the real number" step — production generation itself runs on opencode, same account the judge fix (previous entry) only decoupled the *judge* from, not generation. B2 (model-swap branch decision) and B3 (prompt-edit batch + `make record-golden`) both need real generation calls too. A cron reminder is set to check opencode's `/usage` endpoint and resume the model-swap experiment once the rolling window actually resets.

## Phase B0 (partial): strip schema:dateModified from live-eval scoring (2026-09-06)

Implemented Finding B-1's fix from the Post-PR#45 investigation above: `schema:dateModified` (injected as "today" by `CDIFDiscoveryProfile._inject_envelope`, not extracted by any agent) was dragging down every one of live-eval's 6 fixture scores for a wall-clock gap that will never close, not a real quality difference. New `eval_common.strip_ignored_fields()` (+ `IGNORED_SCORING_FIELDS` set, currently just this one field) strips it from both `actual_json` and `expected_json` in `run_live_eval.py` before either scorer (GEval or the per-field judge) ever sees it — same fix reaches both, since both read the same two stripped strings. `judge_models.py`/`compare_models.py` don't need this: they score DataCite-shaped output via `extract_*`/`compare_outputs`, and DataCite has no equivalent field.

Verified: `ruff`/`mypy` clean, 4 new tests in `tests/test_eval_common.py`, `--help` smoke-checked.

**Not done in this pass** (needs a decision, see below): B0's other two items — fixing `sample_input05`'s golden publisher fixture (Open Question O-5) and re-running `make live-eval` to see the corrected number — are blocked/paused. `make live-eval` is blocked on opencode's quota exactly like the model-swap experiment (production generation runs on opencode, same account the earlier judge-provider fix only decoupled scoring from, not generation). O-5 turned out to be a bigger finding than a fixture edit — see below.

### O-5 investigation: this is a real ROR false-positive, not just a fixture curation call

Checked ROR's real API (`https://api.ror.org/organizations/04q93ds34`) directly rather than assuming, per this doc's own verify-before-implementing discipline. Result: that ROR ID is **"Instituto de Políticas y Bienes Públicos" (IPP)** — a research **facility in Madrid, Spain**. `sample_input05`'s input `publisher` is `"Oficina de Estudios y Políticas Agrarias"` (ODEPA), Chile's real agricultural-policy office. These are two unrelated institutions in two different countries; the shared token is just "Políticas". `identifier_enricher.py`'s ROR affiliation matcher assigned this **wrong country, wrong institution** match `confidence: 1.0` (`matched_via: "ror_affiliation"`) — full confidence on a false positive.

For contrast, verified the sibling match in the same fixture is correct: the `Ministerio de Agricultura` affiliation resolves to `ror.org/05nqvv719`, confirmed via the same API to be the real Chilean Ministry of Agriculture (aliases include "Chilean Ministry of Agriculture", country: Chile).

This means O-5 isn't "is the fixture right or wrong" (it's wrong) — it's **why did the live ROR fuzzy-matcher pick a wrong country's facility with full confidence**, which is a real bug in `identifier_enricher.py`'s ROR affiliation-matching logic (fuzzy string overlap on a shared word, no country/type sanity check), not a one-off fixture curation slip. Fixing just the fixture value would hide this and reproduce the same wrong match on the next live re-recording. Flagged to the user rather than deciding unilaterally how deep to fix — this is exactly the class of identifier-resolution issue CLAUDE.md calls out as needing a live check before a dev→main PR.

## O-5 resolved: ROR affiliation-match country sanity check (2026-09-06)

Fixed the real bug behind Open Question O-5 (found while investigating `sample_input05`'s fixture, see the "Post-PR#45 investigation" section above): `identifier_resolver.py::_try_ror_affiliation` (ROR's own `?affiliation=` disambiguation service, not gema's own fuzzy matcher — `fuzzy_matcher.match_organization`'s country-hint logic was already correct, it's just the fallback path, never reached here) silently dropped the `country` hint entirely and trusted ROR's `chosen: True` pick with instant `confidence: 1.0, status: "auto"` — no independent sanity check at all, even though the same hint was already threaded to this exact call site's sibling fallback path one function away.

Fix: `_try_ror_affiliation` now accepts `country` and cross-checks the chosen candidate's own country (`ror_client.extract_country`) against it — a real, known mismatch demotes to `confidence=0.5, status="review"`, which `identifier_enricher.py`'s existing `_is_auto` gate already refuses to auto-attach (no changes needed there — this fix is fully covered end-to-end by an existing, generic contract). Does **not** override ROR's own `chosen` pick (still respects ROR's own "trust chosen over score" guidance) — only demotes trust in it. An org with no known country is never penalized, same philosophy the `?query=` fallback path already uses.

Tests: new `TestRORAffiliationCountryMismatch` in `tests/test_identifier_resolver.py` (4 cases: mismatch demotes, match stays auto, no-hint stays auto, unknown-country-not-penalized), using a mock built from ROR's real record for `04q93ds34` (verified via `https://api.ror.org/organizations/04q93ds34` directly, not fabricated).

**Golden fixture left untouched, on purpose — could not verify what to change it to.** Attempted to confirm the fix against the exact real case (`sample_input05`'s "Oficina de Estudios y Políticas Agrarias" / ODEPA, country hint "CL") with a live call against a fresh (uncached) resolver: ROR's own `?affiliation=` endpoint no longer returns a `chosen` candidate for this query at all today (`ror_match: None`) — independent ISNI SRU search found ODEPA correctly on its own (`matched_via: "isni_sru"`, `status: "auto"`, no ROR id). This means ROR's own affiliation index has apparently changed since the fixture was originally recorded (or the original match was itself a live-API boundary case) — the exact wrong-country match this fix targets can no longer be reproduced live to confirm the fixture's *correct* new value (whether the ISNI-only result is now what a real re-recording would produce, or something else). Fabricating a new fixture value without that confirmation would repeat the same mistake this investigation started from. Leave as a known-stale fixture value until a real `make record-golden` run (blocked on opencode's quota like everything else) settles it for real.

Verified: `ruff`/`mypy` clean, `tests/test_identifier_resolver.py` 46 passed (+4 new), full `-m "not live"` suite 1268 passed (+8 total this round).

## Phase A0/A1: CODATA source-check + markdown bake-off (2026-09-06) — do not proceed to A2

Real web access this round (the earlier Post-PR#45 pass had none). Both pre-work steps of Phase A done; verdict is to not adopt CODATA's code and not to treat this bake-off as a case for a `content_format: "markdown"` migration either.

**A0 — CODATA's repo, found and read directly.** `github.com/codata/semantic-croissant`: real, public, Python (FastAPI + the official `mcp` SDK), last pushed 2026-08-31. "croissant-live" is a deployment profile inside this repo, not a separate project; a related-but-distinct repo, `github.com/gdcc/mcp-dataverse` (Dataverse+Croissant MCP, CODATA-funded), also exists and is worth knowing about but isn't what the earlier investigation was pointing at.

**Hard blocker, resolves O-6 outright: `GET /repos/codata/semantic-croissant` returns `"license": null`.** No `LICENSE`/`LICENSE.md`/`COPYING` file at any variant, no SPDX tag, no license header anywhere in the repo (checked directly, not inferred). This isn't an AGPL-3.0 compatibility question — under default copyright, unlicensed public code grants no permission to copy/reuse/vendor at all, full stop. **O-6 answer: no, vendoring is not on the table**, independent of gema's own license.

Even setting the license aside, there's little to gain: the repo's actual HTML→markdown step (`convertors/url_to_croissant.py::fetch_url_markdown()`) is itself just `markdownify.markdownify(html_str, heading_style="ATX")` — the same library already on this bake-off's own shortlist — wrapped in orchestration (cloudscraper → Playwright-on-bot-challenge fallback, BeautifulSoup content-root heuristics, WordPress-cruft stripping, GitHub/YouTube/PDF special cases). No proprietary parsing algorithm worth copying, license or no license. The repo also confirms the other half of the original concern: it does contain full JSON-LD/Croissant *generation* machinery (QLever ingestion, `@context` construction) — the plan's existing recommendation against adopting that stands, now confirmed rather than assumed.

**A1 — real bake-off against all 6 golden fixture URLs**, gema's current `clean_html_to_text` vs. `trafilatura`/`markdownify`/`html2text` (via `uv run --with`, zero project dependency changes):

| Fixture | gema (flat) | trafilatura (md) | markdownify (md) | html2text (md) |
|---|---|---|---|---|
| sample01 (datos.gob.cl) | 72 | 255 | 0 | 1,161 |
| sample02 (rasgos.cl) | 9 | 0 | 0 | 1 |
| sample03 (geoportal.cl climate zones) | 7,508 | 4,448 | 8,727 | 8,610 |
| sample04 (ine.gob.cl EPF survey) | **35** | 2,086 | 24,008 | 24,146 |
| sample05 (geoportal.cl Censo Agropecuario) | 23 | 13 | 14 | 17 |
| sample06 (GFZ Data Services, via doi.org) | 123 | 0 | 0 | 1 |

Only 1 of 6 is a genuine markdown-format win: **sample03**, where the page has no `<article>`/`<main>`/`<nav>` tags, so gema's own extractor and the naive baselines all duplicate the full site-chrome nav block verbatim into the output; `trafilatura`'s boilerplate detection is the one method that cleanly excises it. The other 5 are not format comparisons at all — sample01/02/06 are JS-rendered SPAs where the static HTML has no real content for *any* method to extract (confirmed via a script/style-stripped raw-HTML check), and sample05's live URL now 404s (dead link, unrelated to this investigation).

**sample04's apparent gap (35 vs. up to 24,146 chars) is not a markdown finding — it's a distinct, real bug in gema's own fetcher, worth fixing on its own merits.** This page (ASP.NET WebForms, likely Sitefinity) wraps 82.6% of the entire document in one page-wide `<form method="post" id="aspnetForm">`. `content_fetcher.py`'s `_SKIP_TAGS` includes `"form"` (meant for small search/login widgets) and discards nearly the whole article as a result — verified independently that 9,901 real chars of visible text exist in the static HTML that gema currently throws away. **Filed as a fast-follow, independent of any markdown decision**: narrow `_SKIP_TAGS`'s `"form"` entry (e.g. skip only small/short forms, or add a size-proportion guard) — should recover most of this specific gap without touching the flat-text-vs-markdown question at all. Not yet implemented; the existing `clean_html_to_text` 11-test contract must stay green if picked up.

**Recommendation: do not proceed to Phase A2.** A0 alone is a hard stop (no license, nothing to vendor). A1 doesn't independently justify a markdown migration either — real signal-preservation gains showed up in exactly 1 of the 6 real pages this pipeline actually processes, and the fixture with the biggest apparent gap turned out to be a separate, cheap, independently-worth-fixing bug rather than evidence for markdown. Phase A stops here per its own "if none preserve more signal, stop here" clause; A2-A4 not started. The one concrete action item to come out of this is the narrow, independent `_SKIP_TAGS`/`"form"` fix above.

## Phase B0 complete: real golden re-record; live-eval baseline blocked on invalid judge credentials (2026-09-07)

**Re-record (done).** `make record-golden` run against `opencode:deepseek-v4-flash`, no code changes. Reviewed the diff fixture-by-fixture (not blindly accepted):

- **`sample_input05` (the O-5 case) — confirms the O-5 investigation's prediction.** The re-recorded fixture now resolves both the creator and publisher to `"Oficina de Estudios y Políticas Agrarias"` (ODEPA, the real Chilean input publisher) via `matched_via: "isni_sru"`, `confidence: 1.0`, `status: "auto"`, **no ROR id at all** — exactly the "ISNI-only match, no ROR" shape the O-5 section predicted a live re-recording would produce, now confirmed for real rather than left as a documented guess. The wrong-country Madrid-facility ROR match (`ror.org/04q93ds34`, "Instituto de Políticas y Bienes Públicos") is gone. `schema:copyrightHolder` also now correctly reads `"Oficina de Estudios y Políticas Agrarias"` (Phase B1's actor-fallback cascade firing correctly against the corrected publisher).
- **The other 5 fixtures: no code-caused regression, but real run-to-run model variance was observed and is worth recording honestly rather than glossing over.** No seed on the `opencode` provider means a fresh recording is not a byte-for-byte replay of the old one. Concretely: `sample_input01`'s `schema:additionalType` (previously `"Serie de tiempo"`) came back empty this run; `sample_input03`'s `schema:distribution` (previously 2 real WMS/download entries) and `schema:variableMeasured`/`schema:measurementTechnique` came back empty; `sample_input06`'s `schema:relatedLink`, `schema:additionalType`, `schema:variableMeasured`, and `dqv:hasQualityMeasurement` all came back empty too (the same "4 fields collapsed at once" symptom Phase B3 targets — see below, still reproducing on a fresh, independent recording). Conversely, `sample_input02` — previously the one fully-degenerate recording (empty name/creator/license/identifier) — came back substantially populated this time (real name, description, creator with a resolved ROR id, spatialCoverage). None of this is a regression introduced by anything in this session; it's the same self-consistency gap Finding B-3 already named. `copyrightHolder` (Phase B1's fallback) stayed correctly populated everywhere it was before. Two test files (`tests/test_croissant_export.py`, `tests/test_datacite_export.py`) hardcoded literal content from the old recording and were updated to match the new real values (including the O-5 creator-name change) — these assert real extracted content, not code behavior, so they must track whichever fixture is currently committed.
- Full verification green: `ruff`, `mypy` (0 errors), `-m "not live"` (1334 passed, 1 skipped, 18 deselected), `-m regression` (10 passed, 1 skipped). `cache.db`'s diff confirmed genuinely new content (`cmp` against the pre-run commit differs, sizes differ substantially: 116552 → 102400 bytes after a fresh clear+re-record) — not access-time noise, correctly committed. Commit `5f011bd`.

**Live-eval baseline (blocked, not obtained).** `make live-eval` was run against the freshly-recorded golden set. Result: **not a real number** — every one of the 6 judge/per-field scoring calls to `zai-coding-plan:glm-5.3` failed with `401 Unauthorized — {"error":{"code":"1000","message":"Authentication Failed"}}`, so `run_live_eval.py` fell back to an all-zero mean (`0.000`, reported as FAIL against the 0.75 threshold in `reports/live_eval_20260906_230815.md`). **Verified independently, not just trusted from the script's log**: a direct `curl` against `https://api.z.ai/api/coding/paas/v4/chat/completions` with this environment's own `ZAI_API_KEY` (from `.env`) reproduces the identical 401/1000 outside of gema's code entirely — this is a real, invalid/expired credential on the `zai-coding-plan` account in this environment, not a bug in `run_live_eval.py`, the judge-provider-separation fix, or anything else in this repo. This is the same class of finding the 2026-09-06 eval-tooling entry already flagged once ("real key in this environment turned out to be invalid — 401 — left as a follow-up") — now reproduced and confirmed against the actual judge account specifically, not just noted in passing.

**Consequence**: neither Task 1's "real starting number" nor Task 2/Phase B3's "before/after" live-eval comparison could be obtained this session — both need a working `zai-coding-plan` credential, which this environment does not have. This is a credentials/infrastructure gap, not something fixable from inside the codebase; flagged here plainly rather than fabricating or estimating a number. Whoever has a valid `ZAI_API_KEY` for the `zai-coding-plan` account should re-run `make live-eval` against the now-current golden set to get the real Phase B0 baseline; Phase B3's prompt edits below were verified via `make record-golden`'s fixture diff instead, since that path only needs the (working) `opencode` account.

**O-5 cross-reference**: the "O-5 resolved" section above (2026-09-06) left the golden fixture deliberately untouched because the live case couldn't be reproduced to confirm what value it should carry. This re-recording answers that question for real: the ISNI-only, no-ROR shape is exactly what `sample_input05` now produces, live, end to end. The "known-stale fixture value" line in that section can now be read as resolved, not just hoped-for — no further action needed there.

## Phase B3: prompt-edit batch (2026-09-07)

Three concrete, already-identified prompt edits to `config/agents.yaml`, investigated for real against the current prompt text and fixture evidence before editing (not applied blind), then batched into one `make record-golden` re-record cycle per the plan.

**(a) `classification`'s bail-out gate.** Investigated first: there is no separate "English/non-Chilean" gate in the prompt — it's the single PASO 1 "contexto suficiente" criterion (`schema_about`/`schema_keywords`/`schema_audience` all go empty together when "el texto no dice de qué trata el recurso"), worded purely in terms of topical identifiability. Read against `sample_input06.json` (a real English-language, German-institution active-fault database) — its title/description are clearly topical (fault segmentation, geology), so the gate's own stated criterion should never fire here, yet the entire config is otherwise heavily Chile/Spanish-centric (categories, audience table, every other agent's domain knowledge), which is a plausible way for a model to over-generalize "insufficient context" into "not about a domain I recognize." **Correction on the doc's own prior framing**: neither the fixture committed at the start of this session nor the one Task 1 re-recorded actually showed `sample_input06`'s classification fields collapsed — they were populated in both. The originally-cited "collapsed 4 fields at once" observation traces to the PR#45 live-eval run itself (ephemeral candidate output, never saved to a fixture), not something directly reproducible from the committed golden corpus. Rather than skip the fix for lack of a literal reproduction, added the clarification anyway since the risk it addresses is real and independently verifiable: a 3x isolated re-run of just this fixture (ephemeral cache, no config change) showed the *pre-existing* prompt already producing the collapse in 1 of 3 runs — confirming the failure mode is real and stochastic on this provider (no seed), not hypothetical.

Edit: PASO 1 gained an explicit sentence that the criterion depends only on topical identifiability, "NUNCA del idioma del recurso ni de si trata sobre Chile," plus a worked ❌/✅ example in the ERRORES COMUNES section using the exact `sample_input06`-shaped case (English fault database → should still classify fully, in Spanish category/audience vocabulary per the pre-existing shared rule). After the edit, `sample_input06`'s official re-recording shows `schema:about`, `schema:keywords` (4 entries), and `schema:audience` (3 entries) all populated. A repeat of the same 3x isolated test after the edit was not re-run (would have cost 3 more live calls beyond the recording budget) — the one official re-record is the evidence kept; the pre-edit 1-in-3 collapse rate is recorded above as the baseline this edit is meant to reduce, not eliminate (a single-sample, unseeded provider cannot be made fully deterministic by a prompt edit alone).

**(b) `core_metadata`'s `schema_additional_type`.** Confirmed the doc's claim before editing: the field's own bullet only named 3 example labels inline as bare strings, and all 3 worked `EJEMPLOS` in the prompt leave it empty — zero positive worked demonstrations. Re-checked "5/6 golden fixtures" against the Task 1 re-recording: actually 3/6 that run (`sample_input03`/`04`/`05`; `01` and `06` had come back empty due to the same unseeded-provider variance documented throughout this doc). Added 3 grounded mini-examples directly to the field's bullet (cue → label), each lifted from this corpus's own real values: `"Encuesta"` (`sample_input04`, whose title literally is "Encuesta de..."), `"Capa geoespacial"` (`sample_input03`, a shapefile/GIS layer), `"Serie de tiempo"` (`sample_input01`, whose own description literally says "Esta serie contiene..."). After the edit, the official re-recording shows the field populated in 4/6 fixtures (`01`, `03`, `04`, `05`), each matching one of the 3 grounded labels exactly — a real, visible improvement over the 3/6 (and historically up to 5/6) baseline, though still not universal (`02` and `06` are genuinely different resource shapes the 3 examples don't cover, which is expected — the bullet says "no es una lista cerrada").

**(c) `classification`'s keyword geographic-qualifier consistency.** Confirmed the gap directly from Task 1's fixture diffs before editing: `sample_input01`'s re-recorded keyword list mixed `"...-- Chile"`-qualified and unqualified sibling terms in the same list with no textual reason for the difference — the prompt's only guidance on the faceted "Tema -- Subtema -- País" form was a single bare example, no rule about consistency. Added an explicit rule to PASO 3: a resource's geographic qualifier must be applied to *all* of its keywords or *none* of them, never mixed, with a ❌/✅ example built from `sample_input01`'s own real pre-edit inconsistency. After the edit, all 6 re-recorded fixtures show fully internally-consistent keyword lists (`sample_input05`'s list consistently omits the qualifier since "Isla de Pascua" already carries the geography; the other 5 consistently include `"-- Chile"` on every entry) — the clearest before/after win of the three, visible on every fixture, not just the one used to motivate the rule.

**Full-diff review** (not just the 3 targeted fields, per the plan's own instruction): the remaining churn across all 6 fixtures this cycle — audience list ordering, a lost/gained ROR affiliation match, `schema:relatedLink` entry counts, `schema:variableMeasured`/`dqv:hasQualityMeasurement` appearing on `sample_input06` — all traces to agents this batch never touched (`creators_publishers`, `media_files`) or to fields these edits don't govern. Root cause confirmed, not assumed: `scripts/record_golden.py` unconditionally wipes the entire cache directory on every run (`shutil.rmtree(cache_dir)`), so *every* agent regenerates fresh on *every* `make record-golden` call regardless of which prompt actually changed, and `opencode` still carries no seed — the same run-to-run variance Task 1's entry above already documents in detail. Nothing in this diff traces to code these 3 edits touched.

**Live-eval before/after: blocked, same credential issue as Task 1.** `make live-eval` was re-run against the Phase B3 fixtures; identical result — `401 Unauthorized` from `zai-coding-plan:glm-5.3` on every one of the 6 judge calls, all-zero fallback mean, `reports/live_eval_20260906_233721.md`. No before/after comparison number is available this session for the same reason documented in Task 1's entry above (an invalid `ZAI_API_KEY` in this environment, confirmed independently via direct `curl`, not a code issue). Whoever has a working `zai-coding-plan` credential should run `make live-eval` against this fixture set and compare to the Phase B0 baseline (once that's also obtained for real) to get the real before/after number this phase was meant to produce.

Verified: `ruff`, `mypy` (0 errors), full `-m "not live"` suite (1338 passed, 1 skipped, 18 deselected), `-m regression` (10 passed, 1 skipped). Commit `21ebdb8` (prompt edits + re-recorded fixtures + one test-assertion update for `sample_input01`'s real re-ordered audience list).

## Phase B4: read-only investigation — sample_input03 distribution/variableMeasured gap (2026-09-07)

Read-only per the plan (B4 is "deferred/needs-data" — no fix attempted). `schema:distribution` and `schema:variableMeasured` are both owned by `media_files` (confirmed against `config/agents.yaml`'s `fields:` list for that agent — matches the field-ownership table in `CLAUDE.md`).

**Checked the actual `fetched_content` in `sample_input03.json`'s input directly** (`tests/fixtures/golden/inputs/sample_input03.json`), not just its `description` field. First read looked fine (a short, on-topic excerpt was visible near the front) — but reading the *entire* field revealed it's actually **28,002 characters of raw, unstripped HTML**, starting literally with `<!DOCTYPE html>`, including a full Tailwind/Livewire page shell, inline `<style>` blocks, nav chrome, and JSON blobs HTML-entity-escaped inside `wire:snapshot` attributes (e.g. the WMS URL appears wrapped in `&quot;`-escaped JSON, not as plain text). Confirmed this is exactly the "one is raw unstripped HTML" fixture the Post-PR#45 investigation's Phase A1 bake-off already flagged in general terms, now identified specifically. Also confirmed the pipeline never cleans it: `pipeline.py::_maybe_fetch_content` returns immediately (`if resource.fetched_content or not resource.url: return resource`) whenever `fetched_content` already carries a value, which every golden input fixture's does (they're pre-baked, never re-fetched with the current fetcher) — so `clean_html_to_text` never runs on this content, and the LLM's `media_files` call receives the raw 28KB HTML soup verbatim in its prompt, not clean text.

Ran the real `clean_html_to_text()` extractor against this same raw content directly (not the live pipeline, just the function) to see what the resource *should* look like: it collapses to a clean, dense 3,127-character extraction containing everything needed — both real distribution URLs (`.../wms?request=GetCapabilities` and `.../catalog/download/...`) as plain, unambiguous text, plus the temperature/precipitation/altitude/25-climate-types content that would ground `schema:variableMeasured`.

**Conclusion: this is a content-fetch problem, not (or not only) a prompt/agent gap — confirmed by direct evidence, correcting this doc's earlier "overlaps Feature A" framing into an actual confirmation rather than a vague overlap.** The real signal is present in the input either way, but the *form* it currently reaches the LLM in (28KB of raw HTML with the key facts buried inside escaped-JSON attribute soup) is a materially harder extraction task than the clean 3KB text `clean_html_to_text` would produce from the same source. This plausibly explains — though a controlled A/B on this exact fixture was not run, since Task 3 is read-only per the plan — why `schema:distribution`/`schema:variableMeasured` extraction flipped between fully populated and fully empty across this session's 3 separate re-recordings of `sample_input03` (Task 1's, and Task 2's two): a model is far more likely to reliably extract two URLs and a handful of terms from clean prose than to reliably find the same facts re-escaped inside a `wire:snapshot` JSON blob buried in page chrome, especially with no seed on `opencode` adding its own run-to-run noise on top. **This confirms, rather than narrows, the "overlaps Feature A" note**: re-baking this fixture's `fetched_content` through the real, current fetcher (the same "re-bake the golden corpus... after Phase B lands" step Feature A's own plan already calls for) is the concrete, correctly-sequenced next step for this specific gap — not a `media_files` prompt edit, which would be fixing symptoms of a data-quality problem rather than the problem itself. Whoever picks up Feature A should treat `sample_input03` as a known, already-diagnosed case to check first once that re-bake happens.

**O-1 and O-3 reaffirmed as open, not touched by this session.** `schema:dateModified` semantics (O-1: stay "today," or extract a real resource date) and whether `schema:audience`'s `mediator`/`education_level`/`instructional_method` sub-fields should be scored at all (O-3) are both still open, owner-only questions per their original entries in the Open Questions table above — neither Task 1's re-record, Task 2's prompt batch, nor this Phase B4 investigation resolved or touched either. Flagged here explicitly so they don't read as quietly closed just because nearby sections (B0's `schema:dateModified` stripping-from-scoring fix, B3's classification/audience-adjacent edits) touch related surface area without deciding these two questions.

## Phase B0/B3 resolved: real live-eval number obtained (2026-09-07)

`ZAI_API_KEY` rotated by the user; verified independently before re-running anything (`curl` to `https://api.z.ai/api/coding/paas/v4/chat/completions` → `200`, same check that previously reproduced the `401`). Re-ran `make live-eval` against the current, already-Phase-B3-edited golden set (`opencode:deepseek-v4-flash` production, `zai-coding-plan:glm-5.3` judge, both now real).

**Result: mean overall score 0.767 across all 6 fixtures — PASS against the 0.75 threshold** (`reports/live_eval_20260907_093322.md`). Per-fixture: `sample_input01` 0.900, `sample_input02` 0.900, `sample_input03` 0.700, `sample_input04` 0.700, `sample_input05` 0.700, `sample_input06` 0.700. Each score carries a distinct, real GEval judge reason (spot-checked, not a clamp artifact) — e.g. `sample_input01`'s 0.900 cites a near-field-for-field match with only audience/spatialCoverage phrasing deviations; `sample_input03`'s 0.700 is consistent with the Phase B4 finding above (raw-HTML `fetched_content` making distribution/variableMeasured extraction harder).

**This is a post-B3 number only — no separate pre-B3 baseline was ever obtained** (the credential was dead for both of Task 1's and Task 2's live-eval attempts), so this cannot be reported as a measured "before/after delta." It stands as the first real, current quality number for the CDIF pivot as it exists today, superseding the two all-zero-fallback reports (`reports/live_eval_20260906_230815.md`, `reports/live_eval_20260906_233721.md`) which reflected the dead credential, not model/prompt quality, and should not be read as historical baselines.

Report committed: `reports/live_eval_20260907_093322.md`.

## Standing rules

- No push/PR without fresh, explicit, per-instance authorization.
- Everything lands on `feat/cdif-croissant-pivot-spec` as progressive commits. Run `make lint && make typecheck && make test` (plus `visor/` coverage and fixture re-record once Step 2 lands) before moving to the next step, even without a branch boundary forcing it.
