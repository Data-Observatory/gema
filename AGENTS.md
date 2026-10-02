# AGENTS.md

Guidance for coding agents (Claude Code, Codex, etc.) working in this repository.

> This is the canonical agent guide for the repo. `CLAUDE.md` only imports it (`@AGENTS.md`), so
> edit this file, not that one. Per-directory `AGENTS.md` files add subpackage detail — read the
> relevant one when working deep in a subpackage:
> [`src/metadata_enricher/`](src/metadata_enricher/AGENTS.md),
> [`config/`](src/metadata_enricher/config/AGENTS.md),
> [`llm/`](src/metadata_enricher/llm/AGENTS.md),
> [`schemas/`](src/metadata_enricher/schemas/AGENTS.md),
> [`enrichers/`](src/metadata_enricher/enrichers/AGENTS.md),
> [`exporters/`](src/metadata_enricher/exporters/AGENTS.md),
> [`tests/`](tests/AGENTS.md).

## What this is

`gema` — a multi-agent LLM library that generates scholarly metadata (CDIF Discovery profile, JSON-LD) from minimal resource descriptions (URL, title, description, DOI). DataCite 4.6 is exporter-only (design record: `docs/codata_mcp_croissant_cdifspecs.md`, including its Appendix A — DataCite → CDIF field mapping and Appendix B — decision log). Python 3.11+, uv-managed, `pydantic` v2 + `typer` + `openai`/`instructor`. A separate NiceGUI desktop app, Visor (`visor/`, see [`visor/BUILD.md`](visor/BUILD.md)), runs the same pipeline behind a point-and-click UI.

## Commands

```bash
uv sync --extra dev                                    # install (uv only — never pip install)

make test                                               # pytest -m "not live" + coverage (--cov=metadata_enricher)
make lint                                               # ruff check src/ tests/ scripts/
make typecheck                                          # mypy src/ scripts/ (strict)
make test-regression                                    # golden-output cache-replay, no API key needed
make record-golden                                      # regenerate golden fixtures (needs API key)
make live-eval                                          # real-API LLM-judge quality eval (needs API key)
make live-identifier-check                              # real ROR/ISNI/ORCID calls (tests/test_identifier_resolver_live.py -m live)
make ab-eval                                            # A/B diagnostic: CDIF->DataCite export vs frozen DataCite baseline (cache-replay)
make validate-gt                                        # structural check of tests/fixtures/do_catalog/ground_truth
make visor                                              # run Visor from source (python -m visor.app; needs --extra visor)
make test-visor                                         # Visor test suite (visor/tests, -m "not live")

uv run pytest tests/test_X.py -v                        # single test file
uv run pytest tests/test_X.py::TestClass::test_name -v  # single test
uv run pytest -k "not live"                             # skip tests needing real API keys
uv run pytest -m regression                             # golden-output regression tests only

uv run gema list-schemas
uv run gema list-providers --config config/agents.yaml  # runtime providers (agents.yaml's providers: block)
uv run gema list-known-providers                        # autofill presets from config/providers.yaml (not runtime config)
uv run gema validate examples/sample_input01.json
uv run gema process examples/sample_input01.json --config config/agents.yaml --output output.json
uv run gema process examples/sample_input01.json -o output.json --export datacite --export croissant
```

No Docker, no pre-commit hooks. GitHub Actions CI exists (`.github/workflows/ci.yml` + `visor-build.yml`), gating the branch flow: any branch → PR into `dev` (`ci.yml`: ruff on `src/ tests/ scripts/ visor/`, mypy on `src/` and `visor --exclude visor/tests`, `pytest -m "not live" --cov=metadata_enricher`, `make test-visor`) → PR into `main` (same checks again, plus `visor-build.yml`'s full multi-OS build matrix). A third workflow, `release.yml`, builds Visor executables + a wheel/sdist on `v*.*.*` tags. CI never runs anything marked `live` (real LLM calls/cost) — that stays manual-only. Note the ruff/mypy scope in CI includes `visor/` (a separate subpackage, undocumented here — this file covers `metadata_enricher` only); local `make lint`/`make typecheck` do not cover `visor/`, so a clean local run does not guarantee a clean CI run if `visor/` was touched.

**Branch discipline**: one branch per batch of related fixes/features, PR'd straight into `dev` — not off another feature branch. Only branch off an existing feature branch when there's a real code dependency (can't build/test without it), never just because it's the branch already checked out. A 2026-08-14 incident stacked 4 PRs on top of each other this way; every one showed "MERGED" on GitHub but none had actually reached `dev`, and recovering took a full session (see git history around PRs #17-#25). Land and delete branches promptly instead of letting them accumulate.

## Architecture

```
Input JSON -> FilesystemInputSource -> ResourceDescription
                                             |
                                    PreFlightValidator, Schema Registry -> CDIFDiscoveryProfile
                                             |
                AgentRegistry <- PipelineConfig <- ProviderConfig -> LLMClient factory
                                             |
                       Orchestrator (Kahn topological sort + ThreadPoolExecutor)
                                             |
                          MetadataMerger -> MetadataDocument -> OutputWriter -> JSON
```

`pipeline.py:Pipeline.run()` is the main entry point wired to the CLI's `process` command. Per resource: fetch input -> optional page-content fetch (`enable_content_fetch`, before any agent runs) -> validate -> build agent registry -> orchestrate -> merge -> deterministic fallbacks (`schema:url` from `resource.url`; publisher/creator/copyrightHolder actor cascade) -> optional DOI backfill (`enable_doi_resolution`) -> optional identifier enrichment (`enable_identifier_enrichment`) -> PID validation (on by default) -> optional SHACL check (`validate_shacl_conformance`) -> write output (plus any `--export` siblings). Every step is wrapped so a single resource's failure never blocks the batch (the per-resource loop in `Pipeline.run()`, `pipeline.py:210-233`, plus a `try/except` per step in `_process_resource()` returning `PipelineResult(error=...)`); the CLI exits 1 only when *all* resources fail, 2 on any partial failure or warning.

### The Schema Protocol — the central abstraction

`src/metadata_enricher/schemas/base.py` defines a `Schema` Protocol (9 members: `name`, `version`, `output_model`, `build_output_model`, `validate_output`, `normalize_field`, `merge_agent_results`, `get_field_order`, `get_required_fields`). `CDIFDiscoveryProfile` (`schemas/cdif/discovery/cdif_discovery.py`) is the sole registered generation target — `name = "cdif-discovery"`, output shaped as JSON-LD keyed by CURIE (`schema:name`, `schema:creator`, ...) per CODATA's CDIF Discovery profile (vendored from `doc-corediscovery`, SHA in `VENDORED_SHA.txt`). `DataCiteSchema46` (`schemas/datacite.py`, ~1000 LOC, 18 normalizer methods dispatched via a `_NORMALIZER_DISPATCH` dict built after the class body) is deregistered from `schemas/__init__.py` but still directly importable — used as the export target behind `exporters/datacite.py` and for the A/B diagnostic (`make ab-eval`) against the frozen `tests/fixtures/golden_datacite46_baseline/`. Adding a new metadata standard means implementing this Protocol and registering it in `schemas/__init__.py` — no other code changes needed. `MetadataMerger` just delegates to `Schema.merge_agent_results`.

Exporters (`src/metadata_enricher/exporters/`) convert a finished CDIF `MetadataDocument` into other formats: `datacite.py` and `croissant.py` (pure crosswalks, CLI-reachable via `gema process --export datacite|croissant`) and `dataverse.py` (Dataverse native dataset JSON, with one optional LLM call for the Subject vocabulary configured by `config/dataverse_export.yaml`; library + Visor only, no CLI flag). Visor's Run tab offers CDIF, DataCite and Croissant as download formats, plus Dataverse when its export config loads.

### Agents are pure config, not code

Agents are defined entirely in `config/agents.yaml` (id, fields, prompt, system_prompt, provider, model, temperature, max_tokens, `depends_on`, `context_fields`, `tools`, `extra_body`, `reasoning_effort`) — `BaseAgent` is fully generic. (A deprecated `use_chain_of_thought` key is still accepted — dropped with a warning, so old Visor downloads keep loading.) Adding a new agent requires **no code**, only a new YAML entry. The default config (`schema_name: cdif-discovery`) wires 5 agents for CDIF Discovery (`core_metadata`, `creators_publishers`, `classification`, `rights_funding_citations`, `media_files`) into 3 dependency waves, not 1: wave 1 (parallel) is `core_metadata`, `classification`, `media_files`; wave 2 is `creators_publishers` alone (`depends_on: [core_metadata]`, `context_fields: [schema_name]`, `tools: [lookup_organization]` — a ROR lookup tool from `llm/tools.py` it may call mid-reasoning); wave 3 is `rights_funding_citations` alone (`depends_on: [core_metadata, creators_publishers]`, `context_fields: [schema_publisher]`, for citation formatting). Waves run strictly in order (each needs the prior wave's merged output); agents within one wave run concurrently. Agent fields use CDIF CURIEs as snake_case attribute names (e.g. `schema_name` for `schema:name`) since `agents/base.py` does `getattr(result, field_name)`, which requires a valid Python identifier — the real CURIE lives on each Pydantic field's `alias`. Prompt placeholders (`{url}`, `{title}`, ... any input key) are filled by plain string replacement, and the resource itself is appended under `=== RECURSO A PROCESAR ===`. The frozen pre-pivot config is preserved at `config/legacy/agents_datacite46.yaml` for the A/B diagnostic.

### Orchestrator

Agents run in parallel waves based on `depends_on`, computed via Kahn topological sort; each wave runs on a `ThreadPoolExecutor` (single-agent waves skip the pool). Cycle detection raises `ValueError`. **Never hardcode agent IDs in `orchestrator.py`** — use the registry API (`get_agent_configs()` / `get_dependency_graph()`); this is enforced by `tests/test_orchestrator.py` scanning the source for a hardcoded agent name.

### LLM client middleware stack

Built by `llm/factory.py:create_llm_client()`, bottom-up: `InstructorLLMClient` (OpenAI + Instructor structured output, chat_completions models) **or** `ResponsesLLMClient` (`llm/responses_client.py`, for a provider/model resolving `api_style: responses` — see `src/metadata_enricher/config/models.py`'s `ProviderConfig.effective_api_style()`) -> `RetryableLLMClient` (tenacity transport retry) -> `CachedLLMClient` (diskcache, 7-day TTL at `~/.cache/gema/`). Works with any OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, Ollama, ZAI, OpenCode) — adding a provider is config-only (a new entry in `config/agents.yaml`'s inline `providers:` block), never code. Clients are cached module-globally by a composite key of provider+model+temperature+seed+max_tokens+use_cache+use_retry+extra_body, plus api_style/reasoning_effort (only for a non-default api_style) and an API-key fingerprint (only when an explicit key is passed) (`factory.py:110-129`).

**Retry rules are load-bearing** (`llm/retry.py`, `_is_retryable`): `pydantic.ValidationError` and `ValueError` are **never** retried (they belong to the Instructor layer, not the transport — retrying would loop forever on malformed LLM output). `InstructorRetryException` is **not** blanket-rejected: it is unwrapped to its `__cause__` and retried only if that root cause is itself a retryable transport error (e.g. a sustained 429 that exhausted Instructor's own budget); a genuine validation dead-end is never retried. Transport errors (timeouts, connection errors, HTTP 429, and per-config HTTP 5xx) **are** retried; other 4xx are not.

### Determinism / caching

`cache.py:_make_key` hashes model+response_model+temperature+seed+prompt (plus extra_body/tools/api_style/reasoning_effort, each appended only when set so pre-existing keys stay unchanged) — **not** provider: two providers serving the same model name under the same prompt/temperature/seed would collide. All of these must stay in the key or stale cached outputs can leak across configs. `seed` flows `ProviderConfig` -> `LLMConfig` -> `extra_body={"seed": ...}` on the wire.

## Conventions (deviations from generic Python)

- **`uv` only** — `uv sync --extra dev`, `uv run <cmd>`. Never `pip install`. Lockfile is `uv.lock`.
- **Line length 100** (ruff, not the default 88). Target py311.
- **mypy `strict = true`** — no `Any` escapes, full annotations. Never add `# type: ignore` without a reason comment.
- **`from __future__ import annotations`** as the first import in every module.
- Every Pydantic model sets `model_config = ConfigDict(extra="forbid")` **except** `ResourceDescription` and `MetadataDocument`, which use `extra="allow"` as flexible input/output containers.
- **`SecretStr`** for API keys in pydantic models — use `.get_secret_value()` only when handing off to the client; never log it.
- **src-layout**: `pythonpath = ["src"]` in pytest config.
- **LF line endings** enforced via `.gitattributes`.

## Project-enforced invariants (do not weaken)

- `agents/base.py` **must not** import `dspy` — enforced by `tests/test_base_agent.py` scanning the source.
- `orchestrator.py` **must not** hardcode agent names — enforced by `tests/test_orchestrator.py` scanning the source.
- Unknown MIME types in `enrichers/iana_normalizer.py` are preserved unchanged — never nulled, never raised on.
- A single resource failure in `pipeline.py` must never abort the batch.
- `DataCiteSchema46` uses `"Collections"` with a capital C intentionally (`schemas/datacite.py:722`) — preserves legacy merger behavior; don't "fix" the casing. Applies via the real `exporters/datacite.py` export path now (enforced end-to-end by `tests/test_datacite_export.py::TestMediaFilesAndCollectionsCapitalization`), not live generation.

## Testing

- 1:1 file naming: `tests/test_{module}.py` per `src/metadata_enricher/{module}.py`.
- Sync only — no `pytest-asyncio` in `tests/` (Visor's own suite under `visor/tests/` is the exception — `make test-visor` runs it with NiceGUI's user plugin and `asyncio_mode=auto`). Mocking via `unittest.mock` only — no `pytest-mock`.
- No shared `MockLLMClient`; each test file defines its own Protocol-compliant mock intentionally (tailored per test).
- Three tiers: unit tests (mocked, every commit), regression tests (`-m regression`, cache-replay against committed golden fixtures in `tests/fixtures/golden/`, no API key, `json-semantic-diff` score >= 0.85), and live eval (`scripts/run_live_eval.py`, real API calls, DeepEval `GEval` + hand-rolled per-field LLM-as-judge, pre-release only).
- Regenerate golden fixtures after prompt edits, model upgrades, or dependency bumps that change output shape: `make record-golden` then commit `tests/fixtures/golden/`.
- Mark real-API tests `@pytest.mark.live`; run everything else with `uv run pytest -m "not live"`.
- Live tests stay manual-only, same as `make live-eval` — never wired into `ci.yml`/`visor-build.yml` on either the branch→dev or dev→main gate (external-registry flake/rate-limit risk would block a merge for reasons unrelated to code correctness). Run them periodically by hand instead, and always before merging a change that touches the thing they cover — e.g. identifier resolution (ROR/ISNI/ORCID matching, ROR client parsing, fuzzy-match thresholds/abbreviations) should get a live run (`make live-identifier-check`) before a dev→main PR when that area was touched, not just the mocked unit suite.

## Documentation hygiene

Keep `docs/` minimal. Do not create a new `.md` file (plan, design doc, comparison
writeup, survey) unless the user explicitly asks for one — the default channel for
analysis/planning output is the conversation itself, not a file. When a doc already
in `docs/` finishes its job — every deliverable it planned now exists in the
codebase, or its recommendation was superseded by a different actual decision — treat
it as done and delete it rather than leaving it to rot; git history keeps it
recoverable if ever needed. This applies until the user says otherwise.

## Configuration

Full reference: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

- Runtime config lives at repo-root `config/` (YAML/JSON, not code) — distinct from `src/metadata_enricher/config/` (the loader/models code). Main file: `config/agents.yaml` — schema, agents, **and the runtime `providers:` block** (inline; this is the only provider list `gema process` reads). `config/providers.yaml` is *not* runtime config: it is only the preset pool for Visor's "add a provider" autofill and for `gema list-known-providers` — the pipeline never reads it. Other files: `config/dataverse_export.yaml` (Dataverse export's Subject classifier), `config/eval.yaml` (dev-only eval-script defaults, never read by `src/`).
- Config search order (`src/metadata_enricher/config/loader.py:find_config()`): explicit `--config` -> `./config/agents.yaml` -> `~/.config/gema/agents.yaml` -> `$GEMA_CONFIG` env var.
- `${VAR}` syntax in YAML is expanded via `os.path.expandvars()` before pydantic validation.
- `PipelineConfig` cross-validates at construction (fail-fast): `default_provider` and every `agent.provider` must exist in `providers`; every `agent.depends_on` must exist in `agents`; every `context_fields` entry must be produced by a (transitive) `depends_on` ancestor; every `tools` entry must exist in `llm/tools.py`'s `TOOL_REGISTRY`; no duplicate agent IDs, provider names, or per-provider `model_overrides` entries.
- API keys come from `.env` (copy from `.env.example`): `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `OPENCODE_API_KEY`, `ANTHROPIC_API_KEY`, `ZAI_API_KEY` — only the ones referenced by the providers your agents use are needed. Optional `ORCID_CLIENT_ID`/`ORCID_CLIENT_SECRET` enable ORCID resolution of personal creators.
