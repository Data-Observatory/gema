# tests/

Library test suite: 53 `test_*.py` files, pytest 8+, pytest-cov 5+. Config in
`pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["src"]`,
markers `live` and `regression`). Project-wide test conventions (1:1 naming, sync-only,
`unittest.mock` only, no shared `MockLLMClient`, the three tiers, the live-tests-stay-manual
rule) are in the root [`AGENTS.md`](../AGENTS.md#testing) and aren't repeated here.

## Tiers

| Tier | Selector | Needs | Run by |
|------|----------|-------|--------|
| Unit | default (`-m "not live"`) | nothing (everything mocked) | `make test`, CI |
| Regression | `-m regression` (`test_regression.py`) | nothing: cache-replays `fixtures/golden/cache/`, `json-semantic-diff` ≥ 0.85 | `make test-regression`, `make test`, CI |
| Live | `-m live` (`test_live.py`, `test_identifier_resolver_live.py`, live cases in `test_responses_client.py`) | real API keys / network | manual only: `uv run pytest -m live`, `make live-identifier-check` |

`make test` runs `pytest -m "not live"`, same as CI, so live-marked tests never run. Run
live tests explicitly (`uv run pytest -m live`): note `test_identifier_resolver_live.py`'s
ROR/ISNI cases make real network calls even without keys (only its ORCID cases skip without
`ORCID_CLIENT_ID`/`SECRET`).

## Layout (by area)

| Area | Files |
|------|-------|
| Pipeline core | `test_pipeline_integration`, `test_orchestrator`, `test_agent_registry`, `test_base_agent`, `test_merger`, `test_output`, `test_preflight`, `test_types`, `test_input_source`, `test_cli`, `test_seed_propagation` |
| Config | `test_config_loader`, `test_config_migration`, `test_config_models` |
| LLM stack | `test_llm_client`, `test_llm_factory`, `test_instructor_client`, `test_responses_client`, `test_retry`, `test_cache`, `test_llm_tools` |
| Schemas | `test_schema_registry`, `test_cdif_discovery_schema`, `test_cdif_vendored_artifacts`, `test_shacl_conformance`, `test_datacite_schema` |
| Enrichers | `test_content_fetcher`, `test_country_extractor`, `test_crossref_client`, `test_doi_resolver`, `test_fuzzy_matcher`, `test_iana_normalizer`, `test_identifier_enricher`, `test_identifier_overrides`, `test_identifier_resolver`, `test_identifier_types`, `test_isni_client`, `test_orcid_client`, `test_pid_validator`, `test_ror_client` |
| Exporters | `test_datacite_export`, `test_croissant_export`, `test_dataverse_export` |
| Scripts (`scripts/`) | `test_ab_eval_script`, `test_curate_ror_isni`, `test_do_catalog_common`, `test_eval_common`, `test_generate_ground_truth_schema`, `test_render_comparison_report`, `test_validate_ground_truth` |
| Regression / live | `test_regression`, `test_live`, `test_identifier_resolver_live` |

Visor has its own separate suite in `visor/tests/` (NiceGUI user plugin, `asyncio_mode=auto`),
run via `make test-visor` (and `make test-visor-live` for its one real-LLM end-to-end test).
It's not collected by a plain `pytest` run.

## Fixtures

`conftest.py` holds 3 shared fixtures: `mock_ror_api_response` (ROR v2 JSON, Chilean
institutions), `mock_iana_data` (IANA media-types dict), and `sample_merged_output`. Prefer
in-file fixtures and helper factories for anything else.

| Directory | Contents |
|-----------|----------|
| `fixtures/golden/` | `inputs/`, `expected/` (CDIF output), `cache/cache.db` for regression replay. See its [README](fixtures/golden/README.md) |
| `fixtures/golden_datacite46_baseline/` | Frozen pre-pivot DataCite-generated snapshot, used only by `make ab-eval`. Do not update |
| `fixtures/do_catalog/` | 18 `inputs/` + `ground_truth/` pairs (DataCite-shaped ground truth), `manifest.json`, `ground_truth.schema.json`. Used by eval scripts and `make validate-gt` |
| `fixtures/do_catalog_orcid/` | `inputs/` + `ground_truth/` sampled for personal creators (ORCID path), `manifest.json` |

## Meta-tests (project guards: do not delete or weaken)

| Test | Enforces |
|------|----------|
| `test_base_agent.py` `test_no_dspy_imports` | Scans `agents/base.py` source; fails if `"dspy"` appears |
| `test_orchestrator.py` `test_no_hardcoded_agent_names` | Scans `orchestrator.py` source; fails if the agent name `"explorer"` appears |

## Mock strategy

1. **`unittest.mock.MagicMock` + `patch`**: for HTTP (`httpx`), OpenAI exceptions, registry mocks.
2. **Per-file Protocol-compliant LLM clients**, e.g. `test_cache.py::MockLLMClient`,
   `test_base_agent.py::MockLLMClient`, `test_pipeline_integration.py::FakeLLMClient`
   (subclassed in-test for `complete_with_usage`/`complete_with_tools` variants).
3. **Local helper factories** (`make_agent_config()`, `make_resource()`, ...), defined per file, not in conftest.

Exporter tests must use CDIF-shaped (CURIE-keyed) fixtures, never DataCite-shaped ones (see
[`exporters/AGENTS.md`](../src/metadata_enricher/exporters/AGENTS.md#testing)).
