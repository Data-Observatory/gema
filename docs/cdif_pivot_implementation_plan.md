# CDIF/Croissant Pivot — Implementation Progress

Tracks execution of `docs/codata_mcp_croissant_cdifspecs.md`'s decision record. Updated as branches land. Not a decision record itself — see that file for the "why."

## Locked decisions

- **Enrichment architecture fork: option (A).** `enrichers/identifier_enricher.py`, `enrichers/doi_resolver.py`, `enrichers/pid_validator.py`, `output.py`, `exporters/dataverse.py` get retargeted to read CDIF field names directly off the CDIF-generated `MetadataDocument`. No DataCite-shaped intermediate representation reintroduced.
- Spec file lives at `docs/codata_mcp_croissant_cdifspecs.md` (renamed from root `specs.md`, commit on `feat/cdif-croissant-pivot-spec`).

## Branch sequence

- [ ] **`feat/cdif-vendor-artifacts`** (off `feat/cdif-croissant-pivot-spec`) — vendor real CDIF Discovery artifacts at a chosen commit SHA. No Python logic. Blocked on Open Question #1.
- [ ] **`feat/cdif-pivot-core`** (stacked on vendor-artifacts) — the atomic flip: `CDIFDiscoveryProfile`, registry swap, blast-radius retarget (option A) of the 5 call sites above, `config/agents.yaml` rewrite (schema_name + all 5 prompts + context_fields), `config/migrate.py` comment + warning, `record_golden.py` fix, golden fixture re-record + pre-flip baseline snapshot, all affected test files (`tests/` + `visor/tests/`), `visor/` lint+typecheck+`make test-visor` green. One PR, multiple commits — provably atomic, cannot be split and stay green.
- [ ] **`feat/datacite-exporter`** (off `dev`, after pivot-core merges) — `exporters/datacite.py`: real CDIF→DataCite field mapping (not a normalizer-delegation shortcut), reusing `DataCiteSchema46`'s 18 `_normalize_*` methods / `get_field_order` / `get_required_fields` / `"Collections"` capitalization as the last step only.
- [ ] **`feat/croissant-exporter`** (off `dev`, after pivot-core merges, independent of datacite-exporter) — `exporters/croissant.py`, top-level Dataset fields only, `recordSet` empty until structure fetcher exists.
- [ ] **`feat/structure-fetcher`** (off `dev`, after pivot-core merges, independent of the other two) — scope decision needed first (ship "fetch and store, surface nowhere" vs. skip v1 entirely — Open Question #12).

## Step 1 — `feat/cdif-vendor-artifacts`

- [ ] Resolve Open Question #1 (CDIF repo + commit SHA)
- [ ] Vendor `context.jsonld`, `frame.jsonld`, `schema.json`, `shacl.ttl` verbatim under `src/metadata_enricher/schemas/cdif/discovery/`
- [ ] `VENDORED_SHA.txt` (SHA + repo URL + fetch date)
- [ ] `tests/test_cdif_vendored_artifacts.py`: existence, JSON parses, shacl non-empty, SHA pattern, **open-world shape assertion** (`properties: []`/no root `additionalProperties`/no root `required`)
- [ ] `make lint && make typecheck && make test`

## Step 2 — `feat/cdif-pivot-core`

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

## Step 3 — `feat/datacite-exporter`

- [ ] `exporters/datacite.py`: real CDIF→DataCite mapping table, `DataCiteExportResult{datacite_json, warnings, token_usage}`, delegates to `DataCiteSchema46` normalizers only as the last step
- [ ] Confirm Open Question #8 (LLM call scope — default: none, pure crosswalk)
- [ ] `exporters/__init__.py` re-export
- [ ] `tests/test_datacite_export.py` from **CDIF-shaped** synthetic fixtures; explicit `"Collections"` capitalization regression test
- [ ] New `exporters/AGENTS.md`
- [ ] `make lint && make typecheck && make test`

## Step 4 — `feat/croissant-exporter`

- [ ] Resolve Open Question #9 (Croissant top-level field mapping — direct spec check)
- [ ] `exporters/croissant.py`: top-level Dataset fields, `recordSet` empty/documented placeholder
- [ ] `exporters/__init__.py` re-export
- [ ] `tests/test_croissant_export.py` from CDIF-shaped synthetic fixtures
- [ ] `make lint && make typecheck && make test`

## Step 5 — `feat/structure-fetcher`

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
| 1 | CDIF vendored artifact repo + commit SHA | open |
| 2 | CDIF Discovery field coverage beyond required floor | open |
| 3 | `extra="forbid"` vs `"allow"` on output_model | open |
| 4 | JSON-LD envelope emission site | **resolved**: inside `merge_agent_results` |
| 5 | SHACL/JSON-LD framing execute in v1? | open |
| 6 | Enrichment architecture fork | **resolved: option (A)** |
| 7 | Golden fixture strategy | **resolved**: full replace + baseline snapshot |
| 8 | DataCite export LLM-call scope | open (default: none) |
| 9 | Croissant top-level field mapping | open |
| 10 | Structure fetcher format list / sample strategy | open |
| 11 | Content-fetch vs. structure-fetch ordering | open |
| 12 | Does structure-fetcher ship in v1 at all | open |
| 13 | Where DataCite vocab/affiliation table lives post-rewrite | open |
| 14 | `visor/session_settings.py` override migration | open |
| 15 | `config/migrate.py` hardcoded schema name | **resolved**: keep, add warning |

## Standing rules

- No push/PR without fresh, explicit, per-instance authorization.
- Each branch lands lint+typecheck+test green (plus `visor/` coverage and fixture re-record for Step 2) before the next opens.
