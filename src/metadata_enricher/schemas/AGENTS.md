# schemas/

Pluggable metadata schema layer. **The central abstraction of the project.**

## STRUCTURE

```
schemas/
├── __init__.py     # Module-level registry: auto-registers DataCiteSchema46. get_registry() returns singleton.
├── base.py         # Schema Protocol (8 methods) + SchemaRegistry class
└── datacite.py     # DataCiteSchema46 — reference impl, ~600+ LOC, 18 normalizer methods
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add new schema | Create `myschema.py`, implement `Schema` Protocol, register in `__init__.py` |
| Find a normalizer | `datacite.py` — `_NORMALIZER_DISPATCH` dict built post-class-def |
| Change field ordering | `datacite.py` `get_field_order()` — migrated from `Merger.FIELD_ORDER` |
| Add new DataCite field | Extend `DataCiteOutputModel`, add normalizer method, add to dispatch |

## Schema Protocol (`base.py`)

```python
@runtime_checkable
class Schema(Protocol):
    name: str                               # e.g. "datacite-4.6"
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

## DataCiteSchema46 (`datacite.py`)

- 18 normalizer methods (titles, descriptions, creators, languages, dates, geo, rights, funding, subjects, etc.).
- `_NORMALIZER_DISPATCH` dict maps field → method. Built **after** class definition.
- Contains migrated constants from legacy `Merger` class: `LANG_CODE_MAP`, `FREQUENCY_MAP`, `VALID_RESOURCE_TYPES`, `FIELD_ORDER`.
- **`"Collections"` with capital C is intentional** (line 628) — preserves legacy merger behavior.
- Migration traceability comments throughout: search for `"migrated from Merger"`.

## ANTI-PATTERNS

- **NEVER null or raise on unknown MIME types** — preserved unchanged (design principle from `IANANormalizer`, applies to normalize semantics).
- **NEVER add fields to `DataCiteOutputModel` without a matching normalizer** — `_NORMALIZER_DISPATCH` lookup will miss.
- **NEVER modify `_registry` global from outside** — only `__init__.py` registers at import time.

## NOTES

- Only `DataCiteSchema46` ships. Custom schemas require implementing the Protocol.
- The output_model is what `BaseAgent` passes to `LLMClient.complete(response_model=...)` for Instructor structured output.
