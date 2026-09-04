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
- [ ] Vendor `documents/CDIF-metadata-crosswalks-merged.xlsx` (4th artifact, found during Q2 research, not yet copied into repo)
- [x] Resolve Open Question #3: `extra="allow"` on `output_model`, plus a `model_validator(mode="after")` hard-enforcing the required floor (`@id, @type, @context, schema:name, schema:identifier, schema:dateModified, schema:subjectOf`) and the two conditional groups (`schema:license` OR `schema:conditionsOfAccess`; `schema:url` OR `schema:distribution`) — raises if the floor/groups aren't satisfied, allows anything else through
- [x] `CDIFDiscoveryProfile` (`cdif_discovery.py`) — DONE, commit `9bb0aff`: name/version(read from `VENDORED_SHA.txt`)/output_model/`build_output_model` (cache+digest pattern)/`_NORMALIZER_DISPATCH` (generic shape-based normalizers, not per-field bespoke — see module docstring for why)/the required-floor `model_validator` (both conditional OR-groups). 54 tests, all passing.
- [x] JSON-LD envelope (`@context`/`@id`/`@type`/`dcterms:conformsTo`/`schema:dateModified`/`schema:subjectOf`) injected inside `merge_agent_results` — DONE; dead-link comment above `conformsTo` emission present (spec §8)
- [x] Resolve Open Question #5: yes, execute SHACL + JSON-LD framing in v1
- [x] Added `pyshacl`, `rdflib`, `pyld` to `pyproject.toml` — DONE, commit `8621580`
- [ ] **Not yet done**: `validate_output` doesn't actually run SHACL/framing yet — only the Pydantic required-floor check. SHACL (`shacl.ttl`) as a non-blocking conformance check and JSON-LD framing (`frame.jsonld`) via `pyld` are still TODO — the deps are installed but unused so far.
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
- [ ] `validate_output` still doesn't run SHACL/framing — only the Pydantic required-floor check. Deps installed, unused. Separate follow-up, not blocking.
- [ ] Vendor `documents/CDIF-metadata-crosswalks-merged.xlsx` — already done, see commit `0d2878e` (4th vendored artifact); this line is stale, kept only as a note that it's resolved.
- [ ] Docs: root `AGENTS.md`, `CLAUDE.md`, `schemas/AGENTS.md` (+ new `cdif/` subtree entry, fix stale line refs), `docs/CONFIGURATION.md` (`schema_name` example + dead-URI caveat) — **not yet done, next up**.
- [ ] Resolve Open Question #14 (`visor/session_settings.py` persisted-override migration/reset) — not yet addressed; a real gap for anyone with a pre-pivot persisted override, worth a decision before a dev→main PR.
- [x] Verify: `make lint && make typecheck && make test`, `ruff check visor/`, `mypy visor --exclude visor/tests`, `make test-visor`, `make test-regression` — all done, all green (mypy visor's 37 errors are pre-existing/unrelated, see above).
- [ ] Manual live identifier-resolution check + `make live-eval` before any `dev`→`main` PR — not yet run; the record-golden run above exercised real identifier resolution incidentally but this is a separate, more thorough check called out by CLAUDE.md's live-test rule.

**Step 2 is functionally complete.** The CDIF generation pivot works end to end against a real provider, with real identifier enrichment, and the full test suite (1068 tests) is green. Remaining Step 2 items (docs cleanup, SHACL/framing wiring, visor settings migration) are real but non-blocking follow-ups, not gaps in the core pivot.

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

## Step 5 — Structure fetcher: SKIPPED for v1 (see Backlog)

Decided: not building `enrichers/structure_fetcher.py` now. No consumer exists (`ResourceDescription` has no structure field, `agents/base.py::_build_resource_dict` hardcodes a strict 5-key dict, CDIF DataDescription itself is deferred per spec §2) — building it now would be dead code. Tracked in Backlog below so this doesn't get lost.

## Backlog — deferred, not forgotten

- **Structure fetcher (`enrichers/structure_fetcher.py`).** Explicitly deferred, not dropped. Build this when CDIF DataDescription work actually starts (spec §2/§7/§9). At that point also needs: `ResourceDescription` gaining a structure field, `agents/base.py::_build_resource_dict`'s strict 5-key `dict[str, str]` return type changed to carry it, `PipelineConfig.enable_structure_fetch`, a `Pipeline._maybe_fetch_structure()` step mirroring `_maybe_fetch_content()`, and — the part easy to get wrong — the "measured, never generated" invariant test must target LLM *output* (generated fields ⊆ measured columns) once there's a real prompt path, not just the fetcher's own input handling. Open Questions #10 (format list/sample strategy) and #11 (ordering vs. content-fetch) stay open until this is picked back up.
- **Croissant `recordSet` / CDIF DataStructure profile.** Blocked on the structure fetcher above (spec §3.4, §7).

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

## Standing rules

- No push/PR without fresh, explicit, per-instance authorization.
- Everything lands on `feat/cdif-croissant-pivot-spec` as progressive commits. Run `make lint && make typecheck && make test` (plus `visor/` coverage and fixture re-record once Step 2 lands) before moving to the next step, even without a branch boundary forcing it.
