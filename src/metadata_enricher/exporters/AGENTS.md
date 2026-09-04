# exporters/

Converters from a finished, CDIF Discovery-shaped `MetadataDocument` to another system's
*native* format. Post-pipeline, read-only transforms — never part of the generation path
(`schemas/`), never mutate the document they're given.

## WHAT THIS PACKAGE IS NOT

Not a second `schemas/` implementation. `schemas/base.py`'s `Schema` Protocol builds a
`MetadataDocument` from scratch out of raw `AgentResult`s (an LLM extraction pass). Every
exporter here instead takes an *already-finished* `MetadataDocument` — the CDIF Discovery
profile's own generation output — and transforms it into a different system's shape.
Re-running extraction here would double LLM cost re-deriving facts (title, dates, creators)
the CDIF pipeline already got right.

## STRUCTURE

```
exporters/
├── __init__.py       # Re-exports every exporter's public result type + entry function
├── dataverse.py       # CDIF MetadataDocument -> Dataverse native dataset JSON (POST-ready)
├── datacite.py        # CDIF MetadataDocument -> DataCite 4.6 native dict (reverse crosswalk)
└── croissant.py        # CDIF MetadataDocument -> MLCommons Croissant Dataset JSON-LD
```

## SHARED SHAPE CONTRACT

Every exporter follows the same contract:

```python
@dataclass
class <X>ExportResult:
    <payload>: dict[str, Any]         # dataset_json / datacite_json / croissant_json / ...
    warnings: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


def to_<x>_json(document: MetadataDocument, ...) -> <X>ExportResult:
    ...
```

- **Never throw, always warn.** Every field-builder tolerates missing/malformed input; a
  missing/empty source field is a warning appended to `result.warnings`, never a raised
  exception. This mirrors `pipeline.py`'s single-resource isolation invariant one layer up:
  a bad or partial document must still produce *some* usable, structurally valid export
  plus warnings, never a crash.
- **`token_usage` stays zero unless the exporter genuinely makes an LLM call.** Most
  exporters are pure crosswalks (`datacite.py`, `croissant.py`: always zero — Open Question
  #8 in the plan doc resolved DataCite export to "none, pure crosswalk"). `dataverse.py` is
  the one exception — its Subject classification step is a real, optional LLM call, kept on
  the result for cost visibility. The field exists on every result type for shape parity
  even when always zero, so callers can treat all exporters uniformly.
- **Read via `MetadataDocument.get_field(name, default=None)`**, never `document.fields[name]`
  directly — against `document.fields`, a CURIE-keyed dict (`schema:name`, `schema:creator`,
  ...); any given key may be absent, not just empty.
- **Fabricate only low-stakes placeholder text, never high-stakes claims.** All three
  exporters fall back to a placeholder string for `title`/`name` and `description` when
  missing (safe, obviously a placeholder, always flagged with a warning). None of them
  fabricates a license, a creator, a URL, or a date when the source field is empty —
  inventing any of those is a factual/legal claim, not a formatting nicety, so the field is
  instead omitted with a warning. This split is a deliberate judgment call, not an
  oversight — worth re-checking if a new exporter is added.
- Own `FakeLLMClient`/no-shared-mock convention (project-wide) — no shared `MockLLMClient`
  class across test files.

## `dataverse.py` — CDIF -> Dataverse native dataset JSON

Maps a `MetadataDocument` straight onto Dataverse's citation metadata block shape (`POST
/api/dataverses/:alias/datasets` body). Almost entirely deterministic field-by-field mapping
(title <- `schema:name`, authors <- `schema:creator`, contact email <- `schema:contributor`
role `ContactPerson` else first creator's email, description <- `schema:description`,
keywords <- `schema:keywords`, alternativeURL <- `schema:url` else a resolved DOI).

The one genuinely ambiguous field is **Subject**: a required, small fixed controlled
vocabulary (`SUBJECT_CATEGORIES`, verified live against a real Dataverse 6.11 instance) with
no CDIF/DataCite equivalent — gema's own `schema:keywords` is free text. Picking the right
bucket needs judgment a lookup table can't provide, so this is the *one* optional LLM call
this package makes anywhere: `classify_subject()`, gated behind `DataverseExportConfig.enabled`
/ `to_dataverse_json(..., provider=...)`. Disabled (or no provider given) -> `subject`
defaults to `["Other"]`.

`SUBJECT_CATEGORIES` and `_AUTHOR_IDENTIFIER_SCHEMES` are hardcoded, live-verified controlled
vocabularies (dated comments cite the exact verification date/instance) — this is the right
call here, not a shortcut: unlike a model name, Dataverse's shipped-default citation block
vocabulary is genuinely stable and canonical. Re-verify against a real instance's
`/api/dataverses/:id/metadatablocks?returnDatasetFieldTypes=true` before trusting these
against a heavily customized install.

## `datacite.py` — CDIF -> DataCite 4.6 native dict (the reverse crosswalk)

`DataCiteSchema46` (`schemas/datacite.py`) was deregistered as a *generation* target when
this repo pivoted to CDIF Discovery (`docs/cdif_pivot_implementation_plan.md` Step 2) — it is
kept alive specifically to be this *export* target.

**This is real mapping logic, not delegation.** `DataCiteSchema46`'s `_normalize_*` methods
coerce a decade of loosely-shaped legacy DataCite-agent output into DataCite's fixed shape —
they have no idea how to read a `schema:creator` list or turn `schema:dateModified` into
`dates[]` + `resource.publication_year`. `exporters/datacite.py` contains the actual CDIF ->
DataCite field-by-field mapping (`docs/cdif_pivot_implementation_plan.md`'s "Q2" table, read
in reverse — that table is DataCite -> CDIF, this module runs it backwards).
`DataCiteSchema46`'s normalizers are invoked only as the *last* step: each mapped field's raw,
pre-normalization value (the same loosely-typed shape a legacy DataCite agent's structured
output would have produced) is run through `DataCiteSchema46.normalize_field()`, then the
assembled raw dict through `DataCiteSchema46.validate_output()` — so the emitted JSON gets
DataCite's own defaulting/validation (and its intentional `"Collections"` capital-C key) for
free, instead of duplicating that logic here.

### `DataCiteSchema46` singleton

`DataCiteSchema46.__init__` eagerly parses a ~505KB bundled IANA MIME-type JSON snapshot
(`IANANormalizer`). Before the CDIF pivot this cost was paid once because
`schemas/__init__.py`'s `SchemaRegistry` held one process-wide instance. Since
`DataCiteSchema46` is no longer registered there, `exporters/datacite.py` owns its own
module-level singleton (`_datacite_schema_instance` + `_get_datacite_schema()`), lazily
constructed on first call so repeated `to_datacite_json()` calls in a batch export don't each
re-parse the IANA file.

### Field mapping notes worth knowing before touching this file

- **C3 reversal**: a single `schema:publisher` object plus `schema:provider[]` overflow both
  fold back into DataCite's `publishers` list (DataCite has no cardinality-1 publisher
  concept).
- **`schema:sameAs` vs `schema:relatedLink` stay distinct** on the way back too — identity
  assertions (`alternate_identifiers`) vs. typed relations to a *different* resource
  (`related_identifiers`). Never merge these loops.
- **`prov:wasDerivedFrom` is a separate special case**, not folded into the
  `schema:relatedLink` loop — it maps to DataCite's `IsDerivedFrom` relation type specifically
  (CDIF's own explicit convention, see the Q2 table).
- **`schema:contributor` role handling**: known roles (`Producer`, `ContactPerson`, `Editor`,
  `Maintainer`) fold into DataCite's singular `resource.*` actor slots (`_RESOURCE_ROLE_MAP`).
  Any other role isn't dropped — it becomes an extra `creators` entry carrying the role in
  `contributor_type`, with a warning, since DataCite has no purpose-built slot for an
  arbitrary role.
- **Resource-level vs. per-file media metadata**: `config/agents.yaml`'s `media_files` agent
  prompt deliberately keeps `schema:variableMeasured` / `schema:measurementTechnique` /
  `dqv:hasQualityMeasurement` / `prov:wasGeneratedBy` at the *resource* level, not per-
  `schema:distribution` entry. `_build_media_files()` broadcasts these resource-level values
  onto every produced `media_files[]` entry to match DataCite's per-file shape, and warns
  (rather than silently dropping the data) if that resource-level metadata exists but
  `schema:distribution` is empty.
- **`"Collections"` (capital C) is `DataCiteSchema46`'s own intentional legacy quirk**
  (`schemas/datacite.py`, preserves old merger behavior) — `_normalize_media_files` always
  emits this exact key. `exporters/datacite.py` reads a defensive, forward-looking
  `schema:includedInDataCatalog` per-distribution (or resource-level fallback) into it;
  `tests/test_datacite_export.py` has an explicit end-to-end regression test that the
  capital-C key name survives.
- **`resource.resource_type`'s existing legacy quirk is untouched**: `DataCiteSchema46.
  _normalize_resource` collapses any free-text value not in its fixed `VALID_RESOURCE_TYPES`
  vocabulary down to `"Dataset"` (or `""` for URL-shaped input) — this predates the CDIF pivot
  and is not something this exporter tries to work around; `schema:additionalType`'s richer
  free text still flows through faithfully, this normalizer quirk is just downstream of it.

## `croissant.py` — CDIF -> MLCommons Croissant Dataset JSON-LD

Maps top-level Croissant `Dataset` fields only (`name`, `description`, `license`, `url`,
`creator`, `datePublished`, `distribution`, plus recommended/optional fields) — verified
against the real MLCommons Croissant spec (module docstring cites the exact spec commit/URL
checked; re-verify both the docstring and the field list together if targeting a newer
Croissant version).

**`recordSet` (Croissant's per-column/field structure description) ships empty/absent,
explicitly documented as a placeholder** — blocked on a structure-fetcher enricher that
doesn't exist yet. Never synthesize one from title/description prose; nothing on a CDIF
Discovery document describes a dataset's column structure. See `docs/
cdif_pivot_implementation_plan.md`'s Backlog section (Open Questions #10-12) before starting
that work.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Change Dataverse's Subject classification behavior/prompt | `config/dataverse_export.yaml`, `dataverse.py::classify_subject` |
| Add a new Dataverse controlled-vocabulary check (author identifier scheme, subject) | `dataverse.py`'s `SUBJECT_CATEGORIES` / `_AUTHOR_IDENTIFIER_SCHEMES` — both hand-verified live against a real Dataverse instance, see their comments for how/when |
| Find/extend the CDIF -> DataCite field mapping | `datacite.py` — read `docs/cdif_pivot_implementation_plan.md`'s Q2 table in reverse first |
| Change the verified Croissant top-level field list | `croissant.py`'s module docstring — cites the exact spec commit checked; update both if re-verifying against a newer Croissant version |
| Add Croissant `recordSet` support | Blocked on a structure-fetcher enricher that doesn't exist yet — see `croissant.py`'s module docstring and `docs/cdif_pivot_implementation_plan.md`'s Backlog section (Open Questions #10-12) before starting |
| Shared Person/Organization/PropertyValue entry shape every exporter reads | `enrichers/identifier_enricher.py`'s module docstring — the actual shape gema's CDIF pipeline produces for `schema:creator`/`schema:contributor`/`schema:publisher`/`schema:funding`, not re-derived per exporter |

## CONVENTIONS

- `from __future__ import annotations` first import in every module.
- Function-based modules, not classes — an exporter is a pure transform, there's no instance
  state to carry between calls.
- Helper functions are private (`_build_*`, prefixed underscore) and each handles exactly one
  output field, taking `(document, warnings)` (or just `document` when the field can never
  fail) and returning the mapped value. Mirrors `dataverse.py`'s original layout; the other
  two exporters follow the same pattern deliberately, for a reviewer moving between files to
  recognize the shape immediately.
- Every exporter module's docstring documents what it verified its target format against (a
  spec URL + version/commit, same discipline as `schemas/cdif/discovery/VENDORED_SHA.txt` for
  a vendored artifact) — this is reference material a future re-verification pass needs, not
  decoration.

## TESTING

- `tests/test_dataverse_export.py` / `tests/test_datacite_export.py` /
  `tests/test_croissant_export.py` — synthetic CDIF-shaped fixtures (dicts keyed by CURIE,
  built with `MetadataDocument.set_field`) **and** a real-world check against the committed
  golden fixtures (`tests/fixtures/golden/expected/sample_input0{1..6}.json`) produced by an
  actual CDIF-generating pipeline run.
- Fixtures must always be CDIF-shaped, never DataCite-shaped — a DataCite-shaped fixture
  would let a broken reverse mapping (`datacite.py`) pass silently, since it would just be
  identity-mapped through.
- Each test file defines its own mock LLM client (project-wide convention, no shared
  `MockLLMClient`) for `dataverse.py`'s one optional LLM path.

## ANTI-PATTERNS

- **NEVER let a single malformed field raise out of any `to_<x>_json`** — catch, warn,
  degrade.
- **NEVER silently drop data with no home in the target schema** — warn instead (see the
  unmapped-`schema:contributor`-role and orphaned-media-metadata cases in `datacite.py`
  above).
- **NEVER fabricate a license, creator, URL, or date to satisfy a target format's required
  field** — omit and warn instead (see "Shared shape contract" above).
- **NEVER build a DataCite-shaped test fixture for `test_datacite_export.py`** — always
  CDIF-shaped, CURIE-keyed.
- **NEVER duplicate `DataCiteSchema46`'s normalizer logic in `datacite.py`** — build the raw,
  pre-normalization dict and hand it to `DataCiteSchema46.normalize_field`/`validate_output`
  via the module singleton.
- **NEVER instantiate `DataCiteSchema46()` directly in `datacite.py`** — always go through
  `_get_datacite_schema()`, or the 505KB IANA parse repeats per call.
- **NEVER synthesize a `recordSet`** (or any per-record/per-column structure) in
  `croissant.py` — see that module's docstring for the real blocker.
- **NEVER read `document.get_field("schema:creator")` as a bare list** — it's a
  `{"@list": [...]}` JSON-LD construct as of `CDIFDiscoveryProfile.merge_agent_results`
  (constraint C4 in `docs/cdif_pivot_implementation_plan.md`), unlike `schema:contributor`/
  `schema:publisher` (bare array / single object). Always go through
  `types.jsonld_list_unwrap` (or an exporter's own thin wrapper around it, e.g. `datacite.py`'s
  `_creator_list` / `croissant.py`'s `_as_entry_list`) — never index into it directly.
