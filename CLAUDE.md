# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> This repo also carries a set of `AGENTS.md` files (root, `src/metadata_enricher/`, `src/metadata_enricher/config/`, `src/metadata_enricher/llm/`, `src/metadata_enricher/schemas/`, `tests/`) which contain the same kind of guidance in a more detailed, per-directory form. Read the relevant one when working deep in a subpackage — this file is the entry point and summary.

## What this is

`metadata-enricher` (CLI: `metagen`) — a multi-agent LLM library that generates scholarly metadata (DataCite 4.6 reference implementation) from minimal resource descriptions (URL, title, description, DOI). Python 3.11+, uv-managed, `pydantic` v2 + `typer` + `openai`/`instructor`.

## Commands

```bash
uv sync --extra dev                                    # install (uv only — never pip install)

make test                                               # pytest + coverage (--cov=metadata_enricher)
make lint                                               # ruff check src/ tests/
make typecheck                                          # mypy src/ (strict)
make test-regression                                    # golden-output cache-replay, no API key needed
make record-golden                                      # regenerate golden fixtures (needs API key)
make live-eval                                          # real-API LLM-judge quality eval (needs API key)

uv run pytest tests/test_X.py -v                        # single test file
uv run pytest tests/test_X.py::TestClass::test_name -v  # single test
uv run pytest -k "not live"                             # skip tests needing real API keys
uv run pytest -m regression                             # golden-output regression tests only

uv run metagen list-schemas
uv run metagen list-providers --config config/agents.yaml
uv run metagen validate examples/sample_input01.json
uv run metagen process examples/sample_input01.json --config config/agents.yaml --output output.json
```

No CI/CD, no Docker, no pre-commit hooks — all checks run manually via `Makefile`.

## Architecture

```
Input JSON -> FilesystemInputSource -> ResourceDescription
                                             |
                                    PreFlightValidator <- Schema Registry -> DataCiteSchema46
                                             |
                AgentRegistry <- PipelineConfig <- ProviderConfig -> LLMClient factory
                                             |
                       Orchestrator (Kahn topological sort + ThreadPoolExecutor)
                                             |
                          MetadataMerger -> MetadataDocument -> OutputWriter -> JSON
```

`pipeline.py:Pipeline.run()` is the main entry point wired to the CLI's `process` command: fetch input -> validate -> build agent registry -> orchestrate -> merge -> write output. Every pipeline step is wrapped so a single resource's failure never blocks the batch (`pipeline.py:44-46`); the CLI exits 1 only when *all* resources fail.

### The Schema Protocol — the central abstraction

`src/metadata_enricher/schemas/base.py` defines a `Schema` Protocol (8 methods: `name`, `version`, `output_model`, `validate_output`, `normalize_field`, `merge_agent_results`, `get_field_order`, `get_required_fields`). `DataCiteSchema46` (`schemas/datacite.py`) is the only shipped implementation (~600+ LOC, 18 normalizer methods dispatched via a `_NORMALIZER_DISPATCH` dict built after the class body). Adding a new metadata standard means implementing this Protocol and registering it in `schemas/__init__.py` — no other code changes needed. `MetadataMerger` just delegates to `Schema.merge_agent_results`.

### Agents are pure config, not code

Agents are defined entirely in `config/agents.yaml` (id, fields, prompt, provider, model, temperature, `depends_on`, `use_chain_of_thought`) — `BaseAgent` is fully generic. Adding a new agent requires **no code**, only a new YAML entry. The default config wires 5 sequential agents for DataCite 4.6 (`core_metadata` -> `creators_publishers` -> `classification` -> `rights_funding_citations` -> `media_files`), each depending on the previous. Legacy JSON configs live at `config/legacy/andrea_v3.json` (5 agents) and `config/legacy/agents_v2.json` (18 agents), migratable via `metadata_enricher.config.migrate.migrate_json_to_yaml()` (never modifies the source JSON — writes a `.yaml` sibling).

### Orchestrator

Agents run in parallel waves based on `depends_on`, computed via Kahn topological sort; each wave runs on a `ThreadPoolExecutor` (single-agent waves skip the pool). Cycle detection raises `ValueError`. **Never hardcode agent IDs in `orchestrator.py`** — use the registry API (`get_agent_configs()` / `get_dependency_graph()`); this is enforced by `tests/test_orchestrator.py` scanning the source for a hardcoded agent name.

### LLM client middleware stack

Built by `llm/factory.py:create_llm_client()`, bottom-up: `InstructorLLMClient` (OpenAI + Instructor structured output) -> `RetryableLLMClient` (tenacity transport retry) -> `CachedLLMClient` (diskcache, 7-day TTL at `~/.cache/metagen/`). Works with any OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, Ollama, ZAI, OpenCode) — adding a provider is config-only (`config/providers.yaml`), never code. Clients are cached module-globally by a composite key of provider+model+temperature+seed+max_tokens+use_cache+use_retry.

**Retry rules are load-bearing** (`llm/retry.py`): `pydantic.ValidationError`, `InstructorRetryException`, and `ValueError` are **never** retried (they belong to the Instructor layer, not the transport — retrying would loop forever on malformed LLM output). Transport errors (timeouts, connection errors, HTTP 429, and per-config HTTP 5xx) **are** retried.

### Determinism / caching

`cache.py:_make_key` hashes provider+model+temperature+seed+response_model+prompt — all of these must stay in the key or stale cached outputs can leak across configs. `seed` flows `ProviderConfig` -> `LLMConfig` -> `extra_body={"seed": ...}` on the wire.

## Conventions (deviations from generic Python)

- **`uv` only** — `uv sync --extra dev`, `uv run <cmd>`. Never `pip install`. Lockfile is `uv.lock`.
- **Line length 100** (ruff, not the default 88). Target py311.
- **mypy `strict = true`** — no `Any` escapes, full annotations. Never add `# type: ignore` without a reason comment.
- **`from __future__ import annotations`** as the first import in every module.
- Every Pydantic model sets `model_config = ConfigDict(extra="forbid")` **except** `ResourceDescription` and `MetadataDocument`, which use `extra="allow"` as flexible input/output containers.
- **`SecretStr`** for API keys in pydantic models — use `.get_secret_value()` only when handing off to the client; never log it.
- **src-layout**: `pythonpath = ["src"]` in pytest config; `tests/conftest.py` does `sys.path` surgery (lines 6-12) so `src/metadata_enricher` shadows any legacy flat-layout module.

## Project-enforced invariants (do not weaken)

- `agents/base.py` **must not** import `dspy` — enforced by `tests/test_base_agent.py` scanning the source.
- `orchestrator.py` **must not** hardcode agent names — enforced by `tests/test_orchestrator.py` scanning the source.
- Config migration (`config/migrate.py`) **never** modifies the original JSON — writes a `.yaml` sibling only.
- Unknown MIME types in `enrichers/iana_normalizer.py` are preserved unchanged — never nulled, never raised on.
- A single resource failure in `pipeline.py` must never abort the batch.
- `DataCiteSchema46` uses `"Collections"` with a capital C intentionally (`schemas/datacite.py:628`) — preserves legacy merger behavior; don't "fix" the casing.

## Testing

- 1:1 file naming: `tests/test_{module}.py` per `src/metadata_enricher/{module}.py`.
- Sync only — no `pytest-asyncio`. Mocking via `unittest.mock` only — no `pytest-mock`.
- No shared `MockLLMClient`; each test file defines its own Protocol-compliant mock intentionally (tailored per test).
- Three tiers: unit tests (mocked, every commit), regression tests (`-m regression`, cache-replay against committed golden fixtures in `tests/fixtures/golden/`, no API key, `json-semantic-diff` score >= 0.85), and live eval (`scripts/run_live_eval.py`, real API calls, DeepEval `GEval` + hand-rolled per-field LLM-as-judge, pre-release only).
- Regenerate golden fixtures after prompt edits, model upgrades, or dependency bumps that change output shape: `make record-golden` then commit `tests/fixtures/golden/`.
- Mark real-API tests `@pytest.mark.live`; run everything else with `uv run pytest -m "not live"`.

## Configuration

- Runtime config lives at repo-root `config/` (YAML/JSON, not code) — distinct from `src/metadata_enricher/config/` (the loader/models code). Main file: `config/agents.yaml`; provider connections: `config/providers.yaml`.
- Config search order (`config/loader.py:find_config()`): explicit `--config` -> `./config/agents.yaml` -> `~/.config/metagen/agents.yaml` -> `$METAGEN_CONFIG` env var.
- `${VAR}` syntax in YAML is expanded via `os.path.expandvars()` before pydantic validation.
- `PipelineConfig` cross-validates at construction (fail-fast): `default_provider` and every `agent.provider` must exist in `providers`; every `agent.depends_on` must exist in `agents`; no duplicate agent IDs.
- API keys come from `.env` (copy from `.env.example`): `OPENAI_API_KEY`, `ZAI_API_KEY`, or `OPENCODE_API_KEY`.
