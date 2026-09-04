# CDIF/Croissant Pivot — Implementation Progress

Tracks execution of `docs/codata_mcp_croissant_cdifspecs.md`'s decision record. Updated as branches land. Not a decision record itself — see that file for the "why."

## Locked decisions

- **Enrichment architecture fork: option (A).** `enrichers/identifier_enricher.py`, `enrichers/doi_resolver.py`, `enrichers/pid_validator.py`, `output.py`, `exporters/dataverse.py` get retargeted to read CDIF field names directly off the CDIF-generated `MetadataDocument`. No DataCite-shaped intermediate representation reintroduced.
- Spec file lives at `docs/codata_mcp_croissant_cdifspecs.md` (renamed from root `specs.md`, commit on `feat/cdif-croissant-pivot-spec`).

## Branch

All of it lands on **`feat/cdif-croissant-pivot-spec`** (current branch) as progressive commits — no further branch stack. Steps below are work-order within this one branch, not separate PRs. Rename the branch before opening a PR if a more accurate name is wanted once scope is final (e.g. `feat/cdif-croissant-pivot`).

## Research findings (resolves/narrows several open questions)

**Q1 — CDIF vendoring source, resolved to a concrete candidate.** The real target is **`Cross-Domain-Interoperability-Framework/doc-corediscovery`** at commit `81c28260778426cc61302105fc7191b4db360bc9` (2026-05-16) — this is the *composite application profile* ("full discovery... human-facing content requirements"), not `profile-discovery` (a narrower module that only composes `cdifCore` and adds a handful of discovery-specific extension properties — measurementTechnique, variableMeasured, spatialCoverage, temporalCoverage, dqv:hasQualityMeasurement). Files to vendor from `doc-corediscovery`: `CDIFDiscoveryProfileStructuredSchema.json` (76KB, 27 top-level properties), `CDIFDiscovery-frame.jsonld`, `discoveryRules.shacl`. **There is no standalone `context.jsonld` file** — the original plan's assumption of 4 separate files was wrong; `@context` is embedded directly in the schema and frame files (same `{schema, dcterms, dcat, prov, ...}` prefix map in both). Vendoring plan updated: 3 files, not 4, plus `VENDORED_SHA.txt`.

Confirmed via the real schema: required floor is exactly `@id, @type, @context, schema:name, schema:identifier, schema:dateModified, schema:subjectOf` (matches spec §3.2/§5 verbatim) via `allOf[0].required`, **plus two conditional requirements** not previously called out: `allOf[1]` requires `schema:license` OR `schema:conditionsOfAccess` (anyOf), and `allOf[2]` requires `schema:url` OR `schema:distribution` (anyOf). This means `CDIFDiscoveryProfile.output_model`/`validate_output` needs conditional validation logic (a Pydantic `model_validator`), not just a flat required-fields list — flag this in Step 2's implementation, it changes the shape of `get_required_fields()`'s contract slightly (an OR-group can't be expressed as a flat list the way `DataCiteSchema46._REQUIRED_FIELDS` is).

Full top-level property list (27): `@context, @id, @type, schema:name, schema:description, schema:identifier, schema:additionalType, schema:sameAs, schema:version, schema:inLanguage, schema:dateModified, schema:datePublished, schema:conditionsOfAccess, schema:license, schema:url, schema:distribution, schema:relatedLink, schema:publishingPrinciples, schema:keywords, schema:creator, schema:contributor, schema:publisher, schema:provider, schema:funding, prov:wasGeneratedBy, prov:wasDerivedFrom, schema:subjectOf`. This is the real candidate list for Open Question #2 — narrows "TBD" to "pick a subset of these 27" rather than starting from nothing.

**Q9 — Croissant top-level fields, drafted.** Required: `@context, @type ("sc:Dataset"), dct:conformsTo, description, license, name, url, creator, datePublished`. Recommended: `keywords, publisher, version, dateCreated, dateModified, sameAs, sdLicense, inLanguage`. Croissant-specific: `citeAs, isLiveDataset, distribution`. Good enough to draft `exporters/croissant.py`'s top-level mapping against; still worth a spot-check against the pinned Croissant spec version when writing the actual mapping.

## Step 1 — Vendor CDIF artifacts

- [x] Resolve Open Question #1 — see Research findings above; **pending: user confirms `doc-corediscovery`@`81c28260` is the right pin** before committing vendored files
- [ ] Vendor `schema.json` (from `CDIFDiscoveryProfileStructuredSchema.json`), `frame.jsonld` (from `CDIFDiscovery-frame.jsonld`), `shacl.ttl` (from `discoveryRules.shacl`) verbatim under `src/metadata_enricher/schemas/cdif/discovery/` — no separate context.jsonld (see above)
- [ ] `VENDORED_SHA.txt` (SHA `81c28260778426cc61302105fc7191b4db360bc9` + repo URL + fetch date)
- [ ] `tests/test_cdif_vendored_artifacts.py`: existence, JSON parses, shacl non-empty, SHA pattern, **open-world shape assertion** (no top-level `additionalProperties: false`, no flat top-level `required` — note the real schema uses `allOf`+`anyOf` conditional requirements instead of a flat list, adjust the assertion to check for absence of a *closed* top-level shape rather than absence of any required-ness at all)
- [ ] `make lint && make typecheck && make test`

## Step 2 — CDIF schema + pivot core

- [ ] Resolve Open Question #2 (CDIF field coverage beyond the 7-field floor)
- [ ] Resolve Open Question #3 (`extra="forbid"` vs `"allow"` on `CDIFDiscoveryProfile.output_model`, incl. `allow_partial` interaction)
- [ ] `CDIFDiscoveryProfile` (`cdif_discovery.py`): name/version/output_model/`build_output_model` (cache+digest pattern)/`_NORMALIZER_DISPATCH`
- [ ] JSON-LD envelope (`@context`/`@id`/`@type`/`dcterms:conformsTo`/`schema:dateModified`) injected inside `merge_agent_results`; dead-link comment above `conformsTo` emission (spec §8)
- [ ] Resolve Open Question #5 (SHACL/JSON-LD framing execute in v1, or vendored-but-unused placeholders — new deps `pyshacl`/`rdflib`/`pyld` are a real decision)
- [ ] `schemas/__init__.py`: deregister `DataCiteSchema46`, register `CDIFDiscoveryProfile`
- [ ] `DataCiteSchema46` singleton pattern decided for post-deregistration reuse (avoid re-parsing 505KB IANA JSON per use)
- [ ] Blast-radius retarget (option A, locked): `identifier_enricher.py`, `doi_resolver.py`, `pid_validator.py`, `output.py`, `exporters/dataverse.py` → CDIF field names
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

## Step 5 — Structure fetcher

- [ ] Resolve Open Question #12 (ship in v1 at all, given no consumer until DataDescription)
- [ ] Resolve Open Question #10 (format list, sample strategy, Parquet-as-new-dependency)
- [ ] Resolve Open Question #11 (content-fetch vs. structure-fetch ordering/independence)
- [ ] `enrichers/structure_fetcher.py`: fail-soft, mirrors `content_fetcher.py` contract
- [ ] `config/models.py`: `enable_structure_fetch: bool = False`
- [ ] `pipeline.py`: `_maybe_fetch_structure()` before generation
- [ ] `types.py`: structure field on `ResourceDescription` (decide surfacing given `agents/base.py`'s strict 5-key dict)
- [ ] `enrichers/AGENTS.md`: "measured, never generated" invariant documented; pipeline-integration renumbered
- [ ] `docs/CONFIGURATION.md`: `enable_structure_fetch` row
- [ ] `tests/test_structure_fetcher.py` (negative paths, ordering test); invariant test deferred until a real generation-consumer exists (documented why)
- [ ] `make lint && make typecheck && make test`

## A/B diagnostic (spec §9, manual, not CI-gating)

- [ ] `scripts/ab_eval_cdif_vs_datacite.py` using the Step 2 baseline snapshots
- [ ] Pass over `scripts/eval_common.py`, `run_live_eval.py`, `validate_real_output.py`, `reverse_input.py`, `generate_ground_truth_schema.py`, `tests/fixtures/do_catalog/ground_truth*` (all DataCite-shaped today)

## Open questions log

| # | Question | Status |
|---|----------|--------|
| 1 | CDIF vendored artifact repo + commit SHA | **narrowed**: `doc-corediscovery`@`81c28260`, pending user confirm |
| 2 | CDIF Discovery field coverage beyond required floor | **narrowed**: pick from the real 27-property list above |
| 3 | `extra="forbid"` vs `"allow"` on output_model | open |
| 4 | JSON-LD envelope emission site | **resolved**: inside `merge_agent_results` |
| 5 | SHACL/JSON-LD framing execute in v1? | open |
| 6 | Enrichment architecture fork | **resolved: option (A)** |
| 7 | Golden fixture strategy | **resolved**: full replace + baseline snapshot |
| 8 | DataCite export LLM-call scope | open (default: none) |
| 9 | Croissant top-level field mapping | **drafted**, see Research findings |
| 10 | Structure fetcher format list / sample strategy | open |
| 11 | Content-fetch vs. structure-fetch ordering | open |
| 12 | Does structure-fetcher ship in v1 at all | open |
| 13 | Where DataCite vocab/affiliation table lives post-rewrite | open |
| 14 | `visor/session_settings.py` override migration | open |
| 15 | `config/migrate.py` hardcoded schema name | **resolved**: keep, add warning |

## Standing rules

- No push/PR without fresh, explicit, per-instance authorization.
- Everything lands on `feat/cdif-croissant-pivot-spec` as progressive commits. Run `make lint && make typecheck && make test` (plus `visor/` coverage and fixture re-record once Step 2 lands) before moving to the next step, even without a branch boundary forcing it.
