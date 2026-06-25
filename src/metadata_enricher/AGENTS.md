# metadata_enricher package

Main library package. src-layout — `pythonpath=["src"]` adds this to `sys.path`.

## STRUCTURE

```
metadata_enricher/
├── __init__.py              # Exports __version__ only (minimal public API)
├── py.typed                 # PEP 561 marker
├── cli.py                   # Typer app `metagen` — list-schemas/list-providers/validate/process(stub)
├── pipeline.py              # Pipeline class — end-to-end wiring (works, CLI not wired)
├── orchestrator.py          # Orchestrator — Kahn topological sort + ThreadPoolExecutor
├── merger.py                # MetadataMerger — delegates to Schema.merge_agent_results
├── output.py                # OutputWriter — schema field ordering → JSON file/dir/stdout
├── validation.py            # PreFlightValidator — resource + config + cycle detection
├── types.py                 # Core domain models (see below)
├── cache.py                 # CachedLLMClient + CacheManager (diskcache, 7-day TTL)
├── agents/                  # BaseAgent + AgentRegistry (see ./agents/)
├── config/                  # Pydantic models + YAML loader + migration (see ./config/AGENTS.md)
├── llm/                     # LLMClient middleware stack (see ./llm/AGENTS.md)
├── schemas/                 # Schema Protocol + DataCite 4.6 (see ./schemas/AGENTS.md)
└── input_sources/           # InputSource Protocol + FilesystemInputSource
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Pipeline flow (main) | `pipeline.py` `Pipeline.run()` → fetch → validate → registry → orchestrator → merger |
| Add CLI command | `cli.py` — register on `app = typer.Typer(...)` |
| Change field-merge logic | Delegate to `Schema.merge_agent_results` — merger.py just dispatches |
| Core types | `types.py` — see "Core types" below |
| Pre-execute validation | `validation.py` — has explicit redundant checks with "why" comments |

## CORE TYPES (`types.py`)

| Type | Purpose | `extra` policy |
|------|---------|----------------|
| `ResourceDescription` | Input resource to enrich (url, title, description, doi, fetched_content) | **`allow`** (flexible input) |
| `AgentResult` | One agent's extraction (field_name, value, confidence, error, token_usage) | `forbid` |
| `MetadataDocument` | Canonical intermediate representation (`fields` dict + set/get/merge) | **`allow`** (flexible output) |
| `TokenUsage` | prompt/completion/total tokens; auto-calculates total if 0 | `forbid` |
| `LLMResponse` | Generic LLM wrapper (content, model, usage, raw) | `forbid` |

## CONVENTIONS (THIS PACKAGE)

- `from __future__ import annotations` first import in every module.
- Every Pydantic model sets `model_config = ConfigDict(extra="forbid")` UNLESS it's `ResourceDescription` / `MetadataDocument`.
- All pipeline steps wrapped in `try/except` returning `PipelineResult(error=...)` on failure — never raises.
- `ResourceDescription` flattened to `dict[str, str]` (None→"") before prompt formatting — see `agents/base.py:_build_resource_dict`.
- Logger per module: `logger = logging.getLogger(__name__)`.

## ANTI-PATTERNS

- **NEVER import `dspy` in `agents/base.py`** — enforced by `tests/test_base_agent.py`.
- **NEVER hardcode agent IDs in `orchestrator.py`** — use `registry.get_agent_configs()` / `get_dependency_graph()`.
- **NEVER add fields to pydantic models without updating configs** — `extra="forbid"` raises on unknown.
- **NEVER call `OutputWriter` without a schema** — field ordering comes from `Schema.get_field_order()`.
