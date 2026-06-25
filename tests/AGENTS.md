# tests/

24 pytest files, 1:1 per module. pytest 8+, pytest-cov 5+. Config in `pyproject.toml` `[tool.pytest.ini_options]`.

## STRUCTURE

```
tests/
├── __init__.py                # empty package marker
├── conftest.py                # 3 fixtures + sys.path surgery (see below)
├── test_agent_registry.py
├── test_base_agent.py         # ⚠ meta-test: asserts base.py does NOT import dspy
├── test_cache.py
├── test_cli.py
├── test_config_loader.py
├── test_config_migration.py
├── test_config_models.py
├── test_country_extractor.py  # tests metadata_enricher.enrichers (migrated into src/)
├── test_datacite_schema.py    # 1052 lines — largest test file
├── test_iana_normalizer.py    # tests metadata_enricher.enrichers (migrated into src/)
├── test_input_source.py
├── test_instructor_client.py
├── test_llm_client.py
├── test_llm_factory.py
├── test_merger.py
├── test_orchestrator.py       # ⚠ meta-test: asserts no "explorer" hardcoded
├── test_output.py
├── test_pipeline_integration.py
├── test_preflight.py
├── test_retry.py
├── test_schema_registry.py
└── test_types.py
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add new test | `tests/test_{module}.py` (1:1 naming) |
| Shared fixture | `conftest.py` — only 3 fixtures, prefer in-file |
| Mock LLM client pattern | See "Mock strategy" below |
| Live API test | Mark with `@pytest.mark.live` (config in pyproject.toml:43) |

## CONVENTIONS

- **File naming**: `test_{module_name}.py` ↔ `src/metadata_enricher/{module}.py`.
- **Class grouping**: `class Test{Component}:` with docstring `"""{Component}: what is tested."""`.
- **Method naming**: `test_{behavior}` (e.g., `test_compute_waves_linear`).
- **Module docstring**: `"""Tests for {module path}."""`.
- **Section dividers**: `# ----------` between test class groups.
- **No async tests** — all sync. No `pytest-asyncio`.
- **No `pytest-mock`** — only `unittest.mock.patch` / `MagicMock`.

## conftest.py

**sys.path surgery (lines 6-12)** — ensures `src/metadata_enricher` shadows any flat-layout original at repo root. Required because legacy flat-layout `metadata_enricher.py` may still exist.

**3 fixtures:**
| Fixture | Returns |
|---------|---------|
| `mock_ror_api_response` | ROR API v2 JSON (Chilean institutions) |
| `mock_iana_data` | IANA media types dict (`types`, `name_lookup`, `_metadata`) |
| `sample_merged_output` | Full realistic merger output dict |

## Mock strategy (3 patterns)

1. **`unittest.mock.MagicMock` + `patch`** — for HTTP (`httpx.get`), OpenAI exceptions, registry mocks. Dominant in `test_retry.py`, `test_iana_normalizer.py`.

2. **Custom Protocol-compliant classes** — for `LLMClient`. **No shared mock class** — defined per-file:
   - `test_cache.py::MockLLMClient`
   - `test_base_agent.py::MockLLMClient`
   - `test_pipeline_integration.py::FakeLLMClient`

3. **Helper factory functions** — `make_agent_config()`, `make_registry_mock()`, `make_resource()`, `make_test_config()`, `make_input_file()`. Defined locally per file (not in conftest).

## META-TESTS (PROJECT GUARDS)

| Test | File:Line | Enforces |
|------|-----------|----------|
| `test_base_agent_does_not_import_dspy` | `test_base_agent.py:156-165` | Scans `base.py` source — fails if `"dspy"` present |
| `test_no_hardcoded_agent_names` | `test_orchestrator.py:166-181` | Scans orchestrator source — fails if `"explorer"` present |

These are project invariants — do NOT delete or weaken.

## ANTI-PATTERNS

- **NEVER add `tests/__init__.py` content** — must stay empty (avoid shadowing).
- **NEVER use `pytest-mock` fixture `mocker`** — not in deps. Use `unittest.mock.patch`.
- **NEVER weaken the two meta-tests** — they guard core design decisions.
- **NEVER define a shared `MockLLMClient`** — per-file mocks are intentional (tailored to each test).
- **NEVER run `@pytest.mark.live` tests in CI without API keys** — skip with `-m "not live"`.

## NOTES

- Orphan test scripts exist OUTSIDE this dir: `/test_simple.py`, `/test_creators.py`, `/config/test_simple.py`. They are NOT in `testpaths` and do NOT run with `make test`. Treat as stale.
- `test_creators.py` imports `from agents.registry import AgentRegistry` — references old flat-layout `agents/` (will fail after cleanup).
- All tests synchronous; LLM calls mocked unless `@pytest.mark.live`.
- Coverage: `make test` runs `--cov=metadata_enricher --cov-report=term-missing`.
