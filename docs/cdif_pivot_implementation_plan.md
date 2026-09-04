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
| `creators[].contributor_type` | `schema:contributor` → `Role{roleName}` | Verified |
| `publishers` | `schema:publisher` (single) + overflow → `schema:provider[]` — **single-valued, not an array, see C3** | Verified constraint |
| `rights.rights`/`rights_uri`/`rights_identifier` | `schema:license[]` (string\|`{@id}`\|`LabeledLink`) | Verified |
| `rights.rights_condition` | `schema:conditionsOfAccess` | Verified |
| `rights.rights_holder` | `schema:copyrightHolder` | Verified |
| `funding_references` | `schema:funding[]` → `MonetaryGrant{name, identifier, funder: Organization}` — **funder nests inside the grant, no top-level `schema:funder`** | Verified |
| `citations` | `schema:citation[]` → `ScholarlyArticle{pageStart, pageEnd, isPartOf: PublicationIssue → PublicationVolume}` — **not `prov:wasDerivedFrom`** (that's input-data lineage, a different concept; citations are bibliographic) | Verified |
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

## Step 5 — Structure fetcher: SKIPPED for v1 (see Backlog)

Decided: not building `enrichers/structure_fetcher.py` now. No consumer exists (`ResourceDescription` has no structure field, `agents/base.py::_build_resource_dict` hardcodes a strict 5-key dict, CDIF DataDescription itself is deferred per spec §2) — building it now would be dead code. Tracked in Backlog below so this doesn't get lost.

## Backlog — deferred, not forgotten

- **Structure fetcher (`enrichers/structure_fetcher.py`).** Explicitly deferred, not dropped. Build this when CDIF DataDescription work actually starts (spec §2/§7/§9). At that point also needs: `ResourceDescription` gaining a structure field, `agents/base.py::_build_resource_dict`'s strict 5-key `dict[str, str]` return type changed to carry it, `PipelineConfig.enable_structure_fetch`, a `Pipeline._maybe_fetch_structure()` step mirroring `_maybe_fetch_content()`, and — the part easy to get wrong — the "measured, never generated" invariant test must target LLM *output* (generated fields ⊆ measured columns) once there's a real prompt path, not just the fetcher's own input handling. Open Questions #10 (format list/sample strategy) and #11 (ordering vs. content-fetch) stay open until this is picked back up.
- **Croissant `recordSet` / CDIF DataStructure profile.** Blocked on the structure fetcher above (spec §3.4, §7). Correction (2026-09-04): earlier notes in this doc and `exporters/croissant.py`'s docstring called its absence "a gap" — per the real Croissant 1.1 spec, `recordSet` is simply optional; its absence is fully conformant, not a defect. Framing corrected here; still worth building once there's real column data to put in it, just not because leaving it out is wrong today.

- **Two real, additional shape mismatches surfaced by Step 5.5, deliberately not fixed — Open Questions #16 and #17.** Nested `schema:identifier` cardinality (Person/Organization/MonetaryGrant want singular, gema always builds a list) and `schema:contributor`'s Role-wrapper shape (spec wants the actor nested inside `{"@type":["schema:Role"], "schema:roleName", "schema:contributor": <actor>}`, gema reads/writes a flat `{"schema:name","role","schema:email"}`). See Step 5.5's own writeup for the full detail — not repeated here.
- **Neither `exporters/datacite.py` nor `exporters/croissant.py` is wired into anything yet** — both are reachable only from their own test files, not from `cli.py`, `pipeline.py`, or `visor/`. Not a bug (the deliverable was the exporter module + tests, matching Steps 3/4's own scope), but worth deciding when/how these become reachable from `gema process` or Visor's UI before they're considered "shipped" in the product sense, not just "implemented."

## A/B diagnostic (spec §9, manual, not CI-gating)

- [ ] `scripts/ab_eval_cdif_vs_datacite.py` using the Step 2 baseline snapshots
- [ ] Pass over `scripts/eval_common.py`, `run_live_eval.py`, `validate_real_output.py`, `reverse_input.py`, `generate_ground_truth_schema.py`, `tests/fixtures/do_catalog/ground_truth*` (all DataCite-shaped today)

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
| 13 | Where DataCite vocab/affiliation table lives post-rewrite | open |
| 14 | `visor/session_settings.py` override migration | open |
| 15 | `config/migrate.py` hardcoded schema name | **resolved**: keep, add warning |
| 16 | Nested `schema:identifier` cardinality: vendored schema wants singular on Person/Organization/MonetaryGrant, gema always builds a list | open — see Step 5.5, deliberate deviation, not fixed |
| 17 | `schema:contributor`'s Role wrapper: vendored schema wants `{"@type":["schema:Role"], "schema:roleName", "schema:contributor": <actor>}`, gema reads/writes a flat `{"schema:name","role","schema:email"}` | open — see Step 5.5, real structural mismatch, not fixed |
| 18 | `dcterms:conformsTo` on `schema:subjectOf`: the vendored shapes' `cdifd:metadataProfileProperty` requires *both* `https://w3id.org/cdif/core/1.0` and `.../cdif/discovery/1.0`, but `CDIFDiscoveryProfile._inject_envelope` only emits the discovery URI — every real golden fixture fails this SHACL check for exactly this reason | open — surfaced by Step 6's SHACL conformance check, not fixed (out of scope for that pass) |
| 19 | `schema:citation` is forbidden outright by the vendored shapes (`shacl.ttl`'s `cdifd:citationProperty`: `sh:maxCount 0`, "not recommended... because of semantic ambiguity. Use dcterms:bibliographicCitation... or schema:relatedLink") — but the Q2 mapping table (line ~70) maps `citations` → `schema:citation[]` and marks it **"Verified"**. A real conflict between this repo's own field-mapping decision and the vendored artifact it's supposed to implement, found by Step 6's SHACL check (`sample_input03.json` fails `citationProperty` for exactly this reason) | open — not resolved; Q2's "Verified" label for this row is wrong and needs revisiting, but the actual fix (re-map to `dcterms:bibliographicCitation` or `schema:relatedLink`) touches `exporters/datacite.py`'s reverse mapping too and wasn't done here |
| 20 | `schema:url` appears in no agent's `fields:` list in `config/agents.yaml` and nothing in `src/` writes it at the top level — the `url\|distribution` required OR-group can currently only be satisfied via `schema:distribution`, never via `schema:url`, even though the field exists on `CDIFDiscoveryOutputModel` and `exporters/datacite.py`/`exporters/croissant.py` both read it. `ResourceDescription.url` (always present on input) could satisfy this for free via `_inject_envelope`, but that changes what "the resource has a URL" means (input URL vs. a documented landing page) — a real design decision, not made here | open — surfaced by Step 6's SHACL conformance check (5/6 fixtures fail the `url\|distribution` group); not fixed |

## Standing rules

- No push/PR without fresh, explicit, per-instance authorization.
- Everything lands on `feat/cdif-croissant-pivot-spec` as progressive commits. Run `make lint && make typecheck && make test` (plus `visor/` coverage and fixture re-record once Step 2 lands) before moving to the next step, even without a branch boundary forcing it.
