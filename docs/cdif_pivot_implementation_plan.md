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

**Q9 — Croissant top-level fields, drafted.** Required: `@context, @type ("sc:Dataset"), dct:conformsTo, description, license, name, url, creator, datePublished`. Recommended: `keywords, publisher, version, dateCreated, dateModified, sameAs, sdLicense, inLanguage`. Croissant-specific: `citeAs, isLiveDataset, distribution`. Good enough to draft `exporters/croissant.py`'s top-level mapping against; still worth a spot-check against the pinned Croissant spec version when writing the actual mapping.

## Q2 — Verified DataCite → CDIF field mapping (resolved, research-backed)

Full per-field mapping, verified against the real vendored schema, CDIF's own `CDIF-metadata-crosswalks-merged.xlsx` (150-row DataCite↔schema.org crosswalk in the same vendored commit — the authoritative source, used wherever it has an answer), the CDIF Implementation Guide, the real schema.org machine-readable vocabulary (not recalled), and DCMI Terms. One row per current DataCite field (`src/metadata_enricher/schemas/datacite.py`'s shapes), not per agent — assign to agents/waves when writing `config/agents.yaml` in Step 2.

| DataCite field | CDIF/JSON-LD target | Confidence |
|---|---|---|
| `resource.identifier`/`identifier_type` | `@id` (if resolvable URI) else `schema:identifier` (PropertyValue: `propertyID`←type, `value`, `url`) | Verified |
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
- [x] `schemas/__init__.py`: **registered `CDIFDiscoveryProfile` alongside `DataCiteSchema46`** (not yet deregistering DataCite) — DONE, commit `9bb0aff`. Deliberate intermediate state: lets the new schema be developed/tested without breaking the live DataCite pipeline. The real cutover (deregister DataCite + flip `config/agents.yaml` + fix every `datacite-4.6`-asserting test) is its own atomic sub-step below, not yet started.
- [ ] `DataCiteSchema46` singleton pattern decided for post-deregistration reuse (avoid re-parsing 505KB IANA JSON per use)
- [x] Blast-radius retarget (option A, locked): `identifier_enricher.py`, `doi_resolver.py`, `pid_validator.py`, `output.py`, `exporters/dataverse.py` → CDIF field names — DONE, commit `e59ed53` (5 files + 5 test files rewritten, shared Person/Organization shape convention documented in `identifier_enricher.py`'s module docstring)
- [ ] **Known transient breakage, expected, not yet resolved**: `config/agents.yaml` still targets `datacite-4.6`, so the retargeted enrichers now silently no-op against the still-DataCite-shaped live pipeline output. `test_regression.py`'s 3 golden-fixture similarity checks (creators/publishers similarity drops to 0.0 — previously-attached ROR/ISNI identifiers no longer get attached) and `test_pipeline_integration.py::test_malformed_pid_surfaces_as_warning_by_default` fail as a direct, anticipated consequence. Resolves once the config flip + fixture re-record below land — not before.
- [ ] End-to-end test: CDIF-generated document still gets ROR/ORCID enrichment, DOI resolution, PID validation, non-degenerate Dataverse export
- [ ] `config/agents.yaml`: `schema_name: cdif-discovery`, all 5 `fields:` + `context_fields:` + prompts rewritten to CDIF vocabulary (~70.8K chars of prompt — budget a dedicated review pass)
- [ ] Resolve Open Question #13 (where DataCite closed vocabularies + Chilean affiliation table live after rewrite)
- [ ] `config/migrate.py`: keep `"datacite-4.6"` hardcoded, add comment + `logger.warning`, update docstring Notes
- [ ] `record_golden.py`: fix `-s/--schema` (doesn't drive generation, only `OutputWriter`) — remove or repoint default, clarify `--help`
- [ ] Snapshot pre-flip baseline: `config/legacy/agents_datacite46.yaml`, `tests/fixtures/golden_datacite46_baseline/`
- [ ] `make record-golden` (manual, API key) → regenerate `expected/`+`cache/` in place
- [ ] Update: `tests/test_cli.py`, `test_pipeline_integration.py`, `test_preflight.py`, `test_regression.py`, `test_config_migration.py`, `visor/tests/{test_agents_page,test_bootstrap,test_glue,test_app_e2e}.py`
- [ ] New `tests/test_cdif_discovery_schema.py` (mirrors `test_datacite_schema.py` structure) + registry-contents meta-test
- [ ] Docs: root `AGENTS.md`, `CLAUDE.md`, `schemas/AGENTS.md` (+ new `cdif/` subtree entry, fix stale line refs), `docs/CONFIGURATION.md` (`schema_name` example + dead-URI caveat)
- [ ] Resolve Open Question #14 (`visor/session_settings.py` persisted-override migration/reset)
- [ ] Verify: `make lint && make typecheck && make test` + `ruff check visor/` + `mypy visor --exclude visor/tests` + `make test-visor` + `make test-regression` + fixture diff review + manual smoke run against real provider
- [ ] Manual live identifier-resolution check + `make live-eval` before any `dev`→`main` PR

## Step 3 — DataCite exporter

- [ ] `exporters/datacite.py`: real CDIF→DataCite mapping table, `DataCiteExportResult{datacite_json, warnings, token_usage}`, delegates to `DataCiteSchema46` normalizers only as the last step
- [ ] Confirm Open Question #8 (LLM call scope — default: none, pure crosswalk)
- [ ] `exporters/__init__.py` re-export
- [ ] `tests/test_datacite_export.py` from **CDIF-shaped** synthetic fixtures; explicit `"Collections"` capitalization regression test
- [ ] New `exporters/AGENTS.md`
- [ ] `make lint && make typecheck && make test`

## Step 4 — Croissant exporter

- [ ] Resolve Open Question #9 (Croissant top-level field mapping — direct spec check)
- [ ] `exporters/croissant.py`: top-level Dataset fields, `recordSet` empty/documented placeholder
- [ ] `exporters/__init__.py` re-export
- [ ] `tests/test_croissant_export.py` from CDIF-shaped synthetic fixtures
- [ ] `make lint && make typecheck && make test`

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
| 8 | DataCite export LLM-call scope | open (default: none) |
| 9 | Croissant top-level field mapping | **drafted**, see Research findings |
| 10 | Structure fetcher format list / sample strategy | deferred with the whole feature — see Backlog |
| 11 | Content-fetch vs. structure-fetch ordering | deferred with the whole feature — see Backlog |
| 12 | Does structure-fetcher ship in v1 at all | **resolved: no** — see Backlog, must stay visible |
| 13 | Where DataCite vocab/affiliation table lives post-rewrite | open |
| 14 | `visor/session_settings.py` override migration | open |
| 15 | `config/migrate.py` hardcoded schema name | **resolved**: keep, add warning |

## Standing rules

- No push/PR without fresh, explicit, per-instance authorization.
- Everything lands on `feat/cdif-croissant-pivot-spec` as progressive commits. Run `make lint && make typecheck && make test` (plus `visor/` coverage and fixture re-record once Step 2 lands) before moving to the next step, even without a branch boundary forcing it.
