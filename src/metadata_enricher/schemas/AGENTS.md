# schemas/

Pluggable metadata schema layer. **The central abstraction of the project.**

## STRUCTURE

```
schemas/
├── __init__.py         # Module-level registry: auto-registers CDIFDiscoveryProfile only. get_registry() returns singleton.
├── base.py             # Schema Protocol (8 methods) + SchemaRegistry class
├── datacite.py         # DataCiteSchema46 — deregistered, exporter/diagnostic use only, ~600+ LOC, 18 normalizer methods
└── cdif/
    └── discovery/
        ├── cdif_discovery.py   # CDIFDiscoveryProfile — sole registered generation schema ("cdif-discovery")
        ├── schema.json, frame.jsonld, shacl.ttl, crosswalk.xlsx  # vendored from doc-corediscovery
        └── VENDORED_SHA.txt    # pinned upstream commit SHA + fetch date
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add new schema | Create `myschema.py`, implement `Schema` Protocol, register in `__init__.py` |
| CDIF generation logic | `cdif/discovery/cdif_discovery.py` — `_NORMALIZER_DISPATCH`, `_inject_envelope()`, `_ALIAS_BY_ATTR` |
| Find a DataCite normalizer (exporter-only now) | `datacite.py` — `_NORMALIZER_DISPATCH` dict built post-class-def |
| Change DataCite field ordering | `datacite.py` `get_field_order()` — migrated from `Merger.FIELD_ORDER` |
| Add new DataCite field | Extend `DataCiteOutputModel`, add normalizer method, add to dispatch |
| Add new CDIF field | Extend `CDIFDiscoveryOutputModel` with a snake_case attr + CURIE `alias`, add to `_NORMALIZER_DISPATCH` |

## Schema Protocol (`base.py`)

```python
@runtime_checkable
class Schema(Protocol):
    name: str                               # e.g. "cdif-discovery"
    version: str
    output_model: type[BaseModel]           # Pydantic model for validated LLM output
    def validate_output(raw: dict) -> BaseModel
    def normalize_field(field_name, value) -> object
    def merge_agent_results(results: list[AgentResult]) -> MetadataDocument
    def get_field_order() -> list[str]
    def get_required_fields() -> list[str]
```

## SchemaRegistry (`base.py`)

- `register(schema)` — overwrites if name exists.
- `get(name)` — raises `KeyError` with available list if missing.
- `list_schemas()` — returns registered names.
- Module singleton: `_registry` in `__init__.py`. Use `get_registry()`.

## CDIFDiscoveryProfile (`cdif/discovery/cdif_discovery.py`)

- Sole registered generation schema (`name = "cdif-discovery"`). Output is JSON-LD keyed by CURIE (`schema:name`, `schema:creator`, ...).
- `CDIFDiscoveryOutputModel` fields are snake_case attrs (e.g. `schema_name`) each carrying its real CURIE as a Pydantic `alias` — required because `agents/base.py` does `getattr(result, field_name)`, which needs a valid identifier. `model_config = ConfigDict(extra="allow", populate_by_name=True)`.
- 4 generic shape-based normalizers (`_normalize_string`, `_normalize_string_list`, `_normalize_dict_list`, `_normalize_single_dict`) dispatched via `_NORMALIZER_DISPATCH`, built after the class body — unlike DataCite's per-field bespoke normalizers, since CDIF has no legacy shape to coerce.
- `merge_agent_results` translates every attr name to its CURIE alias via `_ALIAS_BY_ATTR` before writing into `MetadataDocument.fields`, then calls `_inject_envelope()` to add `@id`/`@type`/`@context`/`schema:dateModified`/`schema:subjectOf` (incl. `dcterms:conformsTo` pointing at the CDIF Discovery profile URI — currently a 404, emitted per spec anyway, see code comment). Envelope fields are never agent-generated.
- Required-floor validation is split: `get_required_fields()` stays a lenient flat list (matches `DataCiteSchema46`'s warn-only contract via `MetadataMerger`); the real floor — including both conditional OR-groups (`schema:license` OR `schema:conditionsOfAccess`; `schema:url` OR `schema:distribution`) — lives in a `model_validator(mode="after")` on `CDIFDiscoveryOutputModel`, exercised via `validate_output()`. Not inherited by `build_output_model()`'s per-agent partial subset models.
- `version` reads the pinned upstream SHA from `VENDORED_SHA.txt` at instantiation.
- SHACL (`shacl.ttl`) and JSON-LD framing (`frame.jsonld`) are vendored but **not yet wired** into `validate_output()` — `pyshacl`/`rdflib`/`pyld` are installed dependencies, currently unused.

## DataCiteSchema46 (`datacite.py`) — deregistered, exporter/diagnostic use only

- No longer in `schemas/__init__.py`'s registry; still directly importable (`from metadata_enricher.schemas.datacite import DataCiteSchema46`).
- Used by the (not-yet-built) `exporters/datacite.py` and by the A/B diagnostic (`docs/cdif_pivot_implementation_plan.md` §9) against `tests/fixtures/golden_datacite46_baseline/`.
- 18 normalizer methods (titles, descriptions, creators, languages, dates, geo, rights, funding, subjects, etc.).
- `_NORMALIZER_DISPATCH` dict maps field → method. Built **after** class definition.
- Contains migrated constants from legacy `Merger` class: `LANG_CODE_MAP`, `FREQUENCY_MAP`, `VALID_RESOURCE_TYPES`, `FIELD_ORDER`.
- **`"Collections"` with capital C is intentional** (`datacite.py:724`) — preserves legacy merger behavior.
- Migration traceability comments throughout: search for `"migrated from Merger"`.

## ANTI-PATTERNS

- **NEVER null or raise on unknown MIME types** — preserved unchanged (design principle from `IANANormalizer`, applies to normalize semantics).
- **NEVER add fields to `DataCiteOutputModel` or `CDIFDiscoveryOutputModel` without a matching normalizer** — `_NORMALIZER_DISPATCH` lookup will miss.
- **NEVER modify `_registry` global from outside** — only `__init__.py` registers at import time.
- **NEVER re-instantiate `DataCiteSchema46()` per call once it's used outside the registry** — it eagerly parses a ~505KB bundled IANA JSON; cache a singleton wherever it's constructed post-deregistration.

## NOTES

- `CDIFDiscoveryProfile` is the only generation-target schema; `DataCiteSchema46` is exporter-only. Custom schemas require implementing the Protocol.
- The output_model is what `BaseAgent` passes to `LLMClient.complete(response_model=...)` for Instructor structured output.
