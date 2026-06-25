# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-23
**Commit:** 858fc96
**Branch:** main

## OVERVIEW

`metadata-enricher` (`metagen`) — multi-agent LLM library that generates scholarly metadata (DataCite 4.6 reference impl) from minimal resource descriptions. Python 3.11+, uv-managed, hatchling-built, pydantic-v2 + typer + openai/instructor.

## STRUCTURE

```
proj-metadata-agents/
├── src/metadata_enricher/    # Main package (src-layout). See ./src/metadata_enricher/AGENTS.md
├── tests/                    # 24 pytest files, 1:1 per module. See ./tests/AGENTS.md
├── config/                   # Runtime YAML/JSON configs (NOT code). Legacy in config/legacy/
├── data/iana_media_types.json# Static IANA registry (regen via scripts/generate_iana_data.py)
├── examples/                 # 3 sample input JSON files
├── docs/CONFIGURATION.md     # Config guide
├── scripts/                  # generate_iana_data.py only
├── pyproject.toml            # uv + hatchling + ruff + mypy(strict) + pytest config
├── Makefile                  # install/test/lint/typecheck/run/clean (all via `uv run`)
└── uv.lock                   # Reproducible deps
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add a new metadata schema | `src/metadata_enricher/schemas/` | Implement `Schema` Protocol, register in `schemas/__init__.py` |
| Add a new LLM provider | `src/metadata_enricher/llm/` | OpenAI-compatible; add to `config/providers.yaml` |
| Add a new agent | `config/agents.yaml` only | No code needed — `BaseAgent` is generic |
| Run end-to-end pipeline | `src/metadata_enricher/cli.py` `process` command | T22 wired: `Pipeline.run()` → `OutputWriter.write()`; per-resource error isolation |
| Change retry behavior | `src/metadata_enricher/llm/retry.py` | **Never retry validation errors** — see file |
| Add a post-merge enricher | `src/metadata_enricher/enrichers/` | IANANormalizer, CountryExtractor (migrated from repo-root `enrichers/`) |
| Regenerate IANA data | `scripts/generate_iana_data.py` | Manual; writes to `data/iana_media_types.json` |
| Run a single test | `uv run pytest tests/test_X.py -v` | Mark `@pytest.mark.live` for real API keys |

## CONVENTIONS (DEVIATIONS FROM STANDARD)

- **`uv` only** — never `pip install`. `uv sync --extra dev`, `uv run <cmd>`. Lockfile is `uv.lock`.
- **Line length 100** (not 88). Ruff target py311.
- **mypy `strict = true`** — no `Any` escapes, full annotations required. Never use `as any`, `# type: ignore` without reason.
- **All Pydantic models `extra="forbid"`** — except `ResourceDescription` and `MetadataDocument` (`extra="allow"` for flexible input/output containers).
- **src-layout** — `pythonpath = ["src"]` in pytest config. `conftest.py` does `sys.path` surgery to prevent flat-layout shadowing.
- **LF line endings enforced** via `.gitattributes` (`* text=auto eol=lf`).
- **`from __future__ import annotations`** at top of every module (PEP 563 deferred evaluation).
- **`SecretStr` for API keys** in pydantic models (use `.get_secret_value()`).

## ANTI-PATTERNS (THIS PROJECT — ENFORCED)

- **`base.py` MUST NOT import `dspy`** — enforced by `tests/test_base_agent.py:165` (scans source).
- **Orchestrator MUST NOT hardcode agent names** — enforced by `tests/test_orchestrator.py:166-181` (scans for `"explorer"`). Use registry API.
- **Validation errors MUST NEVER be retried** — `pydantic.ValidationError`, `InstructorRetryException`, `ValueError` belong to Instructor layer, not transport retry. See `llm/retry.py:53-59,181-183`.
- **Original JSON config NEVER modified during migration** — `config/migrate.py:90`. Writes `.yaml` sibling only.
- **Unknown MIME types preserved unchanged** — never null, never raise. `src/metadata_enricher/enrichers/iana_normalizer.py`.
- **Single resource failure MUST NEVER block batch** — `pipeline.py:44-46`. Each resource isolated.
- **`process` CLI is fully wired (T22 complete)** — `cli.py:139-202`. Calls `Pipeline.run()` → `OutputWriter.write()`; per-resource error isolation; exit 1 only when all resources fail.

## UNIQUE STYLES

- **Schema Protocol is the central abstraction** — not DataCite-specific. 8 methods: `name`, `version`, `output_model`, `validate_output`, `normalize_field`, `merge_agent_results`, `get_field_order`, `get_required_fields`.
- **Agent prompts use `str.format_map(SafeDict(...))`** — missing template vars render as `""` instead of `KeyError`. See `agents/base.py:10-14`.
- **LLM client middleware stack** — `InstructorLLMClient → RetryableLLMClient → CachedLLMClient`. Built by `factory.py`, cached by composite key (provider+model+temp+seed+max_tokens+use_cache+use_retry).
- **Orchestrator = Kahn topological sort + ThreadPoolExecutor** — agents run in parallel waves respecting `depends_on`. Single-agent waves skip thread pool. Cycle detection raises `ValueError`.
- **7-day disk cache** — `~/.cache/metagen/`, SHA-256 keyed by prompt+model+response_model. See `cache.py`.
- **`conftest.py` sys.path surgery** — ensures `src/metadata_enricher` shadows any flat-layout original. Lines 6-12.
- **DataCite `"Collections"` capital C is intentional** — `schemas/datacite.py:628`. Preserves legacy merger behavior.

## COMMANDS

```bash
uv sync --extra dev                              # Install
make test                                        # pytest with coverage
make lint                                        # ruff check src/ tests/
make typecheck                                   # mypy src/ (strict)
uv run metagen list-schemas                      # CLI: list schemas
uv run metagen validate examples/sample_input01.json
uv run metagen process <input> --config config/agents.yaml --output out.json  # end-to-end
uv run pytest tests/test_X.py -v -m live         # Real API key tests
uv run pytest -k "not live"                      # Skip live tests
```

## NOTES

- **No CI/CD, no Docker, no pre-commit** — only `Makefile`. All checks run manually.
- **`.env` required** — copy `.env.example` to `.env`, fill `OPENAI_API_KEY` / `ZAI_API_KEY` / `OPENCODE_API_KEY`.
- **Config search order** — `find_config()`: explicit `--config` → `./config/agents.yaml` → `~/.config/metagen/agents.yaml` → `$METAGEN_CONFIG`.
- **YAML env var expansion** — `${VAR}` syntax supported in configs via `os.path.expandvars()` (`loader.py:50`).
- **Pipeline + CLI work end-to-end** (`pipeline.py`, `cli.py:process`); per-resource error isolation, exit 1 only on total failure.
- **Only DataCite 4.6 ships** — custom schemas must implement `Schema` Protocol.
- **DSPy teleprompter planned, not implemented** — prompt optimization is future work.
