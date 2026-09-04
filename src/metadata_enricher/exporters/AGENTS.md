# exporters/

Converters from a finished, CDIF-generated `MetadataDocument` into other systems' native
formats. NOT `Schema` Protocol implementations (`schemas/base.py`) — that Protocol builds a
`MetadataDocument` from raw `AgentResult`s (extraction from scratch), which isn't what's
needed here: re-running a full extraction pass would double LLM cost re-deriving facts the
CDIF pipeline already got right. These modules transform an already-finished document
instead.

## STRUCTURE

```
exporters/
├── __init__.py       # Re-exports every exporter's public result type + entry function
├── dataverse.py       # CDIF MetadataDocument -> Dataverse native dataset JSON
└── croissant.py       # CDIF MetadataDocument -> MLCommons Croissant Dataset JSON-LD
```

## SHARED SHAPE CONTRACT

Every exporter follows the same contract:

```python
@dataclass
class <X>ExportResult:
    <payload>: dict[str, Any]         # dataset_json / croissant_json / ...
    warnings: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


def to_<x>_json(document: MetadataDocument, ...) -> <X>ExportResult:
    ...
```

- **Never throw, always warn.** A missing/empty source field is a warning appended to
  `result.warnings`, never an exception. This mirrors `pipeline.py`'s single-resource
  isolation invariant one layer up: a bad or partial document must still produce *some*
  usable export.
- **`token_usage` stays zero unless the exporter genuinely makes an LLM call.** Most
  exporters are pure crosswalks (`croissant.py`: always zero). `dataverse.py` is the one
  exception — its Subject classification step is a real, optional LLM call, kept on the
  result for cost visibility. The field exists on every result type for shape parity
  even when always zero, so callers can treat all exporters uniformly.
- **Read `document.get_field(name, default=None)`**, never `document.fields[name]`
  directly — a CDIF-generated document's fields dict is agent-populated and any given
  CURIE key may be absent, not just empty.
- **Fabricate only low-stakes placeholder text, never high-stakes claims.** `dataverse.py`
  and `croissant.py` both fall back to a placeholder string for `title`/`name` and
  `description` when missing (safe, obviously a placeholder, always flagged with a
  warning). Neither fabricates a license, a creator, a URL, or a date when the source
  field is empty — inventing any of those is a factual/legal claim, not a formatting
  nicety, so the field is instead omitted with a warning. This split is a deliberate
  judgment call, not an oversight — worth re-checking if a new exporter is added.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Change Dataverse's Subject classification behavior/prompt | `config/dataverse_export.yaml`, `dataverse.py::classify_subject` |
| Add a new Dataverse controlled-vocabulary check (author identifier scheme, subject) | `dataverse.py`'s `SUBJECT_CATEGORIES` / `_AUTHOR_IDENTIFIER_SCHEMES` — both hand-verified live against a real Dataverse instance, see their comments for how/when |
| Change the verified Croissant top-level field list | `croissant.py`'s module docstring — cites the exact spec commit checked; update both if re-verifying against a newer Croissant version |
| Add Croissant `recordSet` support | Blocked on a structure-fetcher enricher that doesn't exist yet — see `croissant.py`'s module docstring and `docs/cdif_pivot_implementation_plan.md`'s Backlog section (Open Questions #10-12) before starting |
| Shared Person/Organization/PropertyValue entry shape both exporters read | `enrichers/identifier_enricher.py`'s module docstring — the actual shape gema's CDIF pipeline produces for `schema:creator`/`schema:contributor`/`schema:publisher`/`schema:funding`, not re-derived per exporter |

## CONVENTIONS

- `from __future__ import annotations` first import in every module.
- Function-based modules, not classes — an exporter is a pure transform, there's no
  instance state to carry between calls.
- Helper functions are private (`_build_*`, prefixed underscore) and each handles exactly
  one output field, taking `(document, warnings)` (or just `document` when the field can
  never fail) and returning the mapped value. Mirrors `dataverse.py`'s original layout;
  `croissant.py` follows the same pattern deliberately, for a reviewer moving between the
  two files to recognize the shape immediately.
- Every exporter module's docstring documents what it verified its target format against
  (a spec URL + version/commit, same discipline as `schemas/cdif/discovery/VENDORED_SHA.txt`
  for a vendored artifact) — this is reference material a future re-verification pass
  needs, not decoration.

## ANTI-PATTERNS

- **NEVER synthesize a `recordSet`** (or any per-record/per-column structure) from title/
  description prose in `croissant.py` — nothing on a CDIF Discovery document describes a
  dataset's column structure. See that module's docstring for the real blocker.
- **NEVER fabricate a license, creator, URL, or date to satisfy a target format's required
  field** — omit and warn instead (see "Shared shape contract" above).
- **NEVER assume `schema:creator`/`schema:publisher`'s shape without checking
  `identifier_enricher.py`'s docstring first** — it has changed once already
  (`docs/cdif_pivot_implementation_plan.md`'s constraint-C4 draft assumed an
  `{"@list": [...]}` wrapper; the shipped `CDIFDiscoveryOutputModel.schema_creator` is a
  bare list). Read defensively (tolerate both shapes) where cheap to do so, the way
  `croissant.py::_as_entry_list` does.
