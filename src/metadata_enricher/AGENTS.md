# metadata_enricher package

Main library package. src-layout — `pythonpath=["src"]` adds this to `sys.path`.

## STRUCTURE

```
metadata_enricher/
├── __init__.py              # Exports __version__ only (minimal public API)
├── py.typed                 # PEP 561 marker
├── cli.py                   # Typer app `gema` — list-schemas/list-providers/list-known-providers/validate/process (+ --export)
├── pipeline.py              # Pipeline class — end-to-end wiring (fully wired to CLI)
├── orchestrator.py          # Orchestrator — Kahn topological sort + ThreadPoolExecutor
├── merger.py                # MetadataMerger — delegates to Schema.merge_agent_results
├── output.py                # OutputWriter — schema field ordering → JSON file/dir/stdout
├── validation.py            # PreFlightValidator — resource + config + cycle detection
├── types.py                 # Core domain models (see below)
├── cache.py                 # CachedLLMClient + CacheManager (diskcache, 7-day TTL)
├── agents/                  # BaseAgent (generic, config-driven) + AgentRegistry
├── config/                  # Pydantic models + YAML loader + migration (see ./config/AGENTS.md)
├── llm/                     # LLMClient middleware stack (see ./llm/AGENTS.md)
├── schemas/                 # Schema Protocol + CDIFDiscoveryProfile (generation) + DataCiteSchema46 (exporter-only) (see ./schemas/AGENTS.md)
├── enrichers/               # content_fetcher (pre-agent page fetch), doi_resolver, identifier_* (ROR/ISNI/ORCID),
│                            #   pid_validator, country_extractor, iana_normalizer (see ./enrichers/AGENTS.md)
├── exporters/               # CDIF -> datacite.py / croissant.py / dataverse.py (see ./exporters/AGENTS.md)
└── input_sources/           # InputSource Protocol + FilesystemInputSource
```

### `exporters/` — not a Schema Protocol implementation

`exporters/` converts an already-finished CDIF `MetadataDocument` into another system's
native format: `datacite.py` (DataCite 4.6, reverse crosswalk through `DataCiteSchema46`),
`croissant.py` (MLCommons Croissant JSON-LD), and `dataverse.py` (Dataverse native
dataset JSON). Deliberately **not** extra `Schema` implementations: the `Schema` Protocol
builds a document from raw `AgentResult`s, which would mean re-running a full LLM
extraction pass just to re-derive facts (title, dates, creators) the CDIF pipeline
already got right. DataCite and Croissant are pure crosswalks, reachable from the CLI via
`gema process --export datacite|croissant`. Dataverse makes one optional LLM call
(`classify_subject()`, configured by `config/dataverse_export.yaml`) for its fixed Subject
vocabulary, and is reachable from Visor and the library only. Details and invariants:
[`exporters/AGENTS.md`](exporters/AGENTS.md).

## WHERE TO LOOK

| Task | File |
|------|------|
| Pipeline flow (main) | `pipeline.py` `Pipeline.run()` → fetch input → content fetch (opt-in) → `_process_resource()`: validate → registry → orchestrator → merger → fallbacks → DOI/identifier enrichment → PID/SHACL checks |
| Add CLI command | `cli.py` — register on `app = typer.Typer(...)` |
| Change field-merge logic | Delegate to `Schema.merge_agent_results` — merger.py just dispatches |
| Core types | `types.py` — see "Core types" below |
| Pre-execute validation | `validation.py` — has explicit redundant checks with "why" comments |

## CORE TYPES (`types.py`)

| Type | Purpose | `extra` policy |
|------|---------|----------------|
| `ResourceDescription` | Input resource to enrich (url, title, description, doi, fetched_content) | **`allow`** (flexible input) |
| `AgentResult` | One agent's extraction (field_name, value, confidence, raw_llm_response, error, token_usage) | `forbid` |
| `MetadataDocument` | Canonical intermediate representation (`fields` dict + set/get/merge) | **`allow`** (flexible output) |
| `TokenUsage` | prompt/completion/total tokens + served `model`; auto-calculates total if 0 | `forbid` |

Shared JSON-LD helpers also live here: `jsonld_list_unwrap()` (read `schema:creator`'s
`{"@list": [...]}` wrapper — never index it directly) and `entity_identifiers()` (read a
Person/Organization's singular `schema:identifier` plus its `schema:sameAs` overflow).

## CONVENTIONS (THIS PACKAGE)

- `from __future__ import annotations` first import in every module.
- Every Pydantic model sets `model_config = ConfigDict(extra="forbid")` UNLESS it's `ResourceDescription` / `MetadataDocument`.
- All pipeline steps wrapped in `try/except` returning `PipelineResult(error=...)` on failure — never raises.
- `ResourceDescription` flattened to `dict[str, str]` (None→"", plus `detected_country`) before prompt formatting, which is plain `{key}` string replacement — see `agents/base.py:_build_resource_dict` / `BaseAgent.run()`.
- Logger per module: `logger = logging.getLogger(__name__)`.

## ANTI-PATTERNS

- **NEVER import `dspy` in `agents/base.py`** — enforced by `tests/test_base_agent.py`.
- **NEVER hardcode agent IDs in `orchestrator.py`** — use `registry.get_agent_configs()` / `get_dependency_graph()`.
- **NEVER add fields to pydantic models without updating configs** — `extra="forbid"` raises on unknown.
- **NEVER call `OutputWriter` without a schema** — field ordering comes from `Schema.get_field_order()`.
