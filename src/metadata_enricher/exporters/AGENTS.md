# exporters/

Converters from a finished, CDIF Discovery-shaped `MetadataDocument` to another system's *native* format. Post-pipeline, read-only transforms — never part of the generation path (`schemas/`), never mutate the document they're given.

## STRUCTURE

```
exporters/
├── __init__.py       # Re-exports: DataCiteExportResult, DataverseExportResult,
│                      #   load_dataverse_export_config, to_datacite_json, to_dataverse_json
├── dataverse.py       # CDIF MetadataDocument -> Dataverse native dataset JSON (POST-ready)
└── datacite.py        # CDIF MetadataDocument -> DataCite 4.6 native dict (reverse crosswalk)
```

## WHAT THIS PACKAGE IS NOT

This is **not** a second `schemas/` implementation. `schemas/base.py`'s `Schema` Protocol builds a `MetadataDocument` from scratch out of raw `AgentResult`s (an LLM extraction pass). Both exporters here instead take an *already-finished* `MetadataDocument` — the CDIF Discovery profile's own generation output — and transform it into a different system's shape. Re-running extraction here would double LLM cost re-deriving facts (title, dates, creators) the CDIF pipeline already got right.

## CONTRACT (both exporters follow this exactly)

- Function-based module, not a class — `to_dataverse_json(document, ...)` / `to_datacite_json(document)`.
- **Never throws, always warns.** Every field-builder tolerates missing/malformed input; problems become `result.warnings: list[str]` entries, never a raised exception. A genuinely malformed document degrades to a mostly-empty but *structurally valid* output plus warnings, never a crash — this is what "graceful, not crashes" means throughout this package.
- A plain `@dataclass` result carrying the native payload, `warnings: list[str]`, and `token_usage: TokenUsage` (from `metadata_enricher.types`) — `DataverseExportResult{dataset_json, warnings, token_usage}` / `DataCiteExportResult{datacite_json, warnings, token_usage}`. `token_usage` stays zero unless the exporter makes a real LLM call.
- Reads via `MetadataDocument.get_field(name, default=None)` against `document.fields` — a CURIE-keyed dict (`schema:name`, `schema:creator`, ...), never a positional/attribute API.
- Own `FakeLLMClient`/no-shared-mock convention (project-wide, see `tests/AGENTS.md` if present) — no shared mock class across test files.

## `dataverse.py` — CDIF -> Dataverse native dataset JSON

Maps a `MetadataDocument` straight onto Dataverse's citation metadata block shape (`POST /api/dataverses/:alias/datasets` body). Almost entirely deterministic field-by-field mapping (title <- `schema:name`, authors <- `schema:creator`, contact email <- `schema:contributor` role `ContactPerson` else first creator's email, description <- `schema:description`, keywords <- `schema:keywords`, alternativeURL <- `schema:url` else a resolved DOI).

The one genuinely ambiguous field is **Subject**: a required, small fixed controlled vocabulary (`SUBJECT_CATEGORIES`, verified live against a real Dataverse 6.11 instance) with no CDIF/DataCite equivalent — gema's own `schema:keywords` is free text. Picking the right bucket needs judgment a lookup table can't provide, so this is the *one* optional LLM call this package makes anywhere: `classify_subject()`, gated behind `DataverseExportConfig.enabled` / `to_dataverse_json(..., provider=...)`. Disabled (or no provider given) -> `subject` defaults to `["Other"]`, no warning if it was an intentional disable, a warning if a provider was expected but missing.

`SUBJECT_CATEGORIES` and `_AUTHOR_IDENTIFIER_SCHEMES` are hardcoded, live-verified controlled vocabularies (dated comments cite the exact verification date/instance) — this is the right call here, not a shortcut: unlike a model name, Dataverse's shipped-default citation block vocabulary is genuinely stable and canonical. Re-verify against a real instance's `/api/dataverses/:id/metadatablocks?returnDatasetFieldTypes=true` before trusting these against a heavily customized install.

## `datacite.py` — CDIF -> DataCite 4.6 native dict (the reverse crosswalk)

`DataCiteSchema46` (`schemas/datacite.py`) was deregistered as a *generation* target when this repo pivoted to CDIF Discovery (`docs/cdif_pivot_implementation_plan.md` Step 2) — it is kept alive specifically to be this *export* target.

**This is real mapping logic, not delegation.** `DataCiteSchema46`'s `_normalize_*` methods coerce a decade of loosely-shaped legacy DataCite-agent output into DataCite's fixed shape — they have no idea how to read a `schema:creator` list or turn `schema:dateModified` into `dates[]` + `resource.publication_year`. `exporters/datacite.py` contains the actual CDIF -> DataCite field-by-field mapping (`docs/cdif_pivot_implementation_plan.md`'s "Q2" table, read in reverse — that table is DataCite -> CDIF, this module runs it backwards). `DataCiteSchema46`'s normalizers are invoked only as the *last* step: each mapped field's raw, pre-normalization value (the same loosely-typed shape a legacy DataCite agent's structured output would have produced) is run through `DataCiteSchema46.normalize_field()`, then the assembled raw dict through `DataCiteSchema46.validate_output()` — so the emitted JSON gets DataCite's own defaulting/validation (and its intentional `"Collections"` capital-C key) for free, instead of duplicating that logic here.

No LLM call — Open Question #8 in the plan doc resolved to "none, pure crosswalk"; `token_usage` on `DataCiteExportResult` stays zero always, kept only for shape parity with `dataverse.py`.

### `DataCiteSchema46` singleton

`DataCiteSchema46.__init__` eagerly parses a ~505KB bundled IANA MIME-type JSON snapshot (`IANANormalizer`). Before the CDIF pivot this cost was paid once because `schemas/__init__.py`'s `SchemaRegistry` held one process-wide instance. Since `DataCiteSchema46` is no longer registered there, `exporters/datacite.py` owns its own module-level singleton (`_datacite_schema_instance` + `_get_datacite_schema()`), lazily constructed on first call so repeated `to_datacite_json()` calls in a batch export don't each re-parse the IANA file.

### Field mapping notes worth knowing before touching this file

- **`schema:creator` shape gap, handled defensively.** The vendored `schema.json`'s own field description asks for `schema:creator` to be a JSON-LD `{"@list": [...]}` construct (to preserve author order) — but `CDIFDiscoveryProfile` (Step 2) actually emits it as a bare list today (confirmed against the real recorded golden fixtures). `_creator_list()` accepts either shape rather than silently dropping every creator on whichever shape it doesn't expect. This is a real, currently-open gap between the vendored spec and this repo's generation code, tracked in the plan doc — not something papered over quietly here.
- **C3 reversal**: a single `schema:publisher` object plus `schema:provider[]` overflow both fold back into DataCite's `publishers` list (DataCite has no cardinality-1 publisher concept).
- **`schema:sameAs` vs `schema:relatedLink` stay distinct** on the way back too — identity assertions (`alternate_identifiers`) vs. typed relations to a *different* resource (`related_identifiers`). Never merge these loops.
- **`prov:wasDerivedFrom` is a separate special case**, not folded into the `schema:relatedLink` loop — it maps to DataCite's `IsDerivedFrom` relation type specifically (CDIF's own explicit convention, see the Q2 table).
- **`schema:contributor` role handling**: known roles (`Producer`, `ContactPerson`, `Editor`, `Maintainer`) fold into DataCite's singular `resource.*` actor slots (`_RESOURCE_ROLE_MAP`). Any other role isn't dropped — it becomes an extra `creators` entry carrying the role in `contributor_type`, with a warning, since DataCite has no purpose-built slot for an arbitrary role.
- **Resource-level vs. per-file media metadata**: `config/agents.yaml`'s `media_files` agent prompt deliberately keeps `schema:variableMeasured` / `schema:measurementTechnique` / `dqv:hasQualityMeasurement` / `prov:wasGeneratedBy` at the *resource* level ("a nivel del recurso, no por archivo"), not per-`schema:distribution` entry. `_build_media_files()` broadcasts these resource-level values onto every produced `media_files[]` entry to match DataCite's per-file shape, and warns (rather than silently dropping the data) if that resource-level metadata exists but `schema:distribution` is empty.
- **`"Collections"` (capital C) is DataCiteSchema46's own intentional legacy quirk** (`schemas/datacite.py`, preserves old merger behavior) — `_normalize_media_files` always emits this exact key. `exporters/datacite.py` reads a defensive, forward-looking `schema:includedInDataCatalog` per-distribution (or resource-level fallback) into it; `tests/test_datacite_export.py` has an explicit end-to-end regression test that the capital-C key name survives.
- **`resource.resource_type`'s existing legacy quirk is untouched**: `DataCiteSchema46._normalize_resource` collapses any free-text value not in its fixed `VALID_RESOURCE_TYPES` vocabulary down to `"Dataset"` (or `""` for URL-shaped input) — this predates the CDIF pivot and is not something this exporter tries to work around; `schema:additionalType`'s richer free text still flows through faithfully, this normalizer quirk is just downstream of it.

## TESTING

- `tests/test_dataverse_export.py` / `tests/test_datacite_export.py` — synthetic CDIF-shaped fixtures (dicts keyed by CURIE, built with `MetadataDocument.set_field`) **and** a real-world check against the committed golden fixture (`tests/fixtures/golden/expected/sample_input01.json`) produced by an actual CDIF-generating pipeline run.
- Fixtures must always be CDIF-shaped, never DataCite-shaped — a DataCite-shaped fixture would let a broken reverse mapping pass silently (it would just be identity-mapped through).
- Each test file defines its own mock LLM client (project-wide convention, no shared `MockLLMClient`) for `dataverse.py`'s one optional LLM path.

## ANTI-PATTERNS

- **NEVER let a single malformed field raise out of `to_dataverse_json`/`to_datacite_json`** — catch, warn, degrade.
- **NEVER silently drop data with no home in the target schema** — warn instead (see the unmapped-`schema:contributor`-role and orphaned-media-metadata cases above).
- **NEVER build a DataCite-shaped test fixture for `test_datacite_export.py`** — always CDIF-shaped, CURIE-keyed.
- **NEVER duplicate `DataCiteSchema46`'s normalizer logic in `datacite.py`** — build the raw, pre-normalization dict and hand it to `DataCiteSchema46.normalize_field`/`validate_output` via the module singleton.
- **NEVER instantiate `DataCiteSchema46()` directly in `datacite.py`** — always go through `_get_datacite_schema()`, or the 505KB IANA parse repeats per call.
