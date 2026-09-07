# CDIF/Croissant JSON-LD Pivot — Metadata Generation Architecture Specification

Status: draft v1 · 2026-09-03 · Not yet implemented

This document specifies a change to gema's core generation architecture: the LLM
generation target flips from DataCite 4.6 to CDIF's Discovery profile (JSON-LD),
with DataCite demoted to a downstream export. It also specifies a new file/column
structure-fetching enricher. Decided through an extended adversarial review
(multiple rounds, positions reversed more than once on both sides) after a CODATA
demo of their `semantic-croissant` / `croissant-live` MCP server and CDIF's
Cross-Domain Interoperability Framework. Source discussion is not reproduced here;
this document records only the resulting decisions and their rationale.

---

## 1. Overview & Goals

gema currently generates DataCite 4.6 metadata directly: five LLM agents produce
DataCite-shaped Pydantic output, merged via `DataCiteSchema46.merge_agent_results`
into a `MetadataDocument`. `exporters/dataverse.py` already demonstrates a second
pattern — a deterministic, no-LLM-cost crosswalk from an already-generated
`MetadataDocument` to a different output shape.

Goals for this change:

- Make the **generation pivot** CDIF's Discovery profile (JSON-LD) instead of
  DataCite 4.6, so DataCite becomes one exporter among several rather than the
  only possible output.
- Support **multiple, evolving downstream schemas** without paying LLM cost per
  schema: DataCite 4.6 today, DataCite 4.7 later, OpenAIRE if/when it becomes a
  real target, Croissant for ML-dataset interoperability — all as exporters off
  one generation pass, not N independent generation passes.
- Gain **CDIF conformance** (a stated organizational forward-compatibility
  requirement) without weakening the validation guarantees gema already has.
- Add a **file/dataset-structure fetcher** so gema can eventually describe
  column-level dataset structure (CDIF DataDescription, Croissant `recordSet`) —
  gated behind a hard invariant: structure is *measured*, never *generated*.
- Keep quality and precision non-negotiable; CDIF compatibility is additive,
  not a quality tradeoff (see §3).

## 2. Non-Goals / Out of Scope (v1)

- **Not adopting Croissant as the generation target.** Croissant (`recordSet`/
  `field`) and CDIF's DataStructure profile (`cdifTabularData`/`cdifLongData`/
  `cdifDataCube`, DDI-CDI-based) are independent, non-overlapping schema.org
  JSON-LD models — verified directly in both projects' repos, neither references
  the other. Making either the generation target instead of CDIF Discovery would
  require picking one arbitrarily; instead both are treated as **exporters/
  projections of measured facts** (§7).
- **Not implementing CDIF DataDescription yet.** It requires file/column facts
  the structure fetcher doesn't exist to provide yet. Discovery-only for v1.
- **Not depending on CODATA's hosted MCP server or its ingestion service.**
  Any MCP usage is a self-hosted deployment, entirely outside this repo's scope.
  gema's own structure fetcher is a plain HTTP/parsing enricher, not an MCP
  client.
- **Not chasing CDIF's live, unreleased register.** CDIF has zero tagged
  releases anywhere (`validation`, `profile-discovery`, `metadataBuildingBlocks`,
  `profile-core`, `doc-corediscovery` — verified, all commits on `main`, three
  pushed the same day this was investigated). gema vendors specific artifacts at
  a named commit SHA instead (§6.2).
- **Not integrating ODRL, DID, FAIR Signposting, or QLever/SPARQL into gema.**
  Verified in CODATA's actual `api/main.py`: their real ingestion service has no
  auth of any kind; ODRL/DID lives only in their MCP frontend
  (`api/mcp_server.py`, client-side). None of it is gema's concern.
- **Not targeting OpenAIRE now.** No committed date, no schema decision yet —
  named here only as evidence the exporter-pattern requirement is real and
  open-ended, not as a v1 deliverable.

## 3. Decision & Rationale

### 3.1 Why the pivot flips to CDIF, not why it stays DataCite

`types.py`'s `MetadataDocument` docstring already states it is a "canonical
intermediate representation... NOT DataCite-specific" — the schema-agnostic
pivot already exists structurally. What changes is *which schema the LLM
generates against directly*, and therefore which schema's fields drive prompt
design, agent wave structure, and the primary golden-fixture set.

The deciding argument is the multi-target requirement in §1: N generation
targets cost N× LLM spend and N× fixture maintenance; one generation pass plus
N exporters costs 1×. `exporters/dataverse.py` is proof this pattern already
works in this codebase.

### 3.2 Why this doesn't weaken validation (the objection that took three rounds to resolve)

The concern: DataCite generation today is checked against a **closed** Pydantic
model (`extra="forbid"` project-wide convention) — a hallucinated field dies
loudly at validation instead of silently becoming a new, unchecked value.
Naively targeting raw JSON-LD as an open-world document would lose that.

Resolved by direct inspection of `CDIFDiscoverySchema.json`: CDIF's own root
schema has `properties: []`, no root `additionalProperties`, no root
`required` — it is explicitly **open-world** by CDIF's own design (their
`profile-discovery` README: *"Validation is open-world: unknown properties
pass"*), enforcing only a **minimum required-field floor**
(`@id`, `@type`, `@context`, `schema:name`, `schema:identifier`,
`schema:dateModified`, `schema:subjectOf`).

Because CDIF's validator is permissive, nothing stops gema from being *stricter*
than CDIF requires: derive a **closed** Pydantic model over the CDIF properties
gema actually targets (`CDIFDiscoveryProfile.output_model`, `extra="forbid"`,
same convention as `DataCiteSchema46`), have Instructor constrain generation to
that closed model exactly as it does today, then emit JSON-LD that CDIF's own
open-world validator and SHACL rules (`discoveryRules.shacl`) also accept as an
outer check. **Net result: more validation than today, not less** — a closed
model on the way out, plus CDIF's floor and SHACL as an additional outer layer
gema doesn't currently have.

This does **not** address a different, unrelated risk class: wrong values in
correctly-shaped fields (a fabricated ROR ID, a plausible-but-wrong year). No
schema mechanism — closed model, required floor, or SHACL — catches that. That
risk is what `enrichers/` (ROR/ORCID/ISNI resolution, `identifier_overrides.py`,
`pid_validator.py`) and golden-fixture semantic-diff regression exist for, and
none of this changes under the pivot.

### 3.5 `DataCiteSchema46` becomes exporter-only — decided

`DataCiteSchema46` is **dropped from `schemas/__init__.py`'s Schema Protocol
registry**. It no longer consumes raw `AgentResults` via `merge_agent_results`,
because agents no longer produce DataCite-shaped output — they produce
CDIF-shaped output, consumed by `CDIFDiscoveryProfile.merge_agent_results`
instead. There is exactly one generation-target Schema going forward:
`CDIFDiscoveryProfile`.

`DataCiteSchema46`'s existing normalization logic (18 `_NORMALIZER_DISPATCH`
methods, `get_field_order`, `get_required_fields`, the intentional
`"Collections"` capitalization, etc.) is not discarded — it is reused inside
`exporters/datacite.py` (§4), adapted to crosswalk from an already-generated,
CDIF-populated `MetadataDocument` rather than from raw agent output. This is
the exact same shape `exporters/dataverse.py` already uses: a deterministic,
no-LLM-cost transform over a finished `MetadataDocument`, not a second
extraction pass. No DataCite-specific normalization knowledge is lost — it
moves from the generation layer to the export layer.

`config/agents.yaml`'s `schema_name` becomes `cdif-discovery`; nothing in the
pipeline references `datacite-4.6` as a generation-time schema name anymore.

### 3.3 Why version stability is satisfied without a tagged release

CDIF has no tags. The `dcterms:conformsTo` URIs CDIF's own spec instructs
implementers to declare (`w3id.org/cdif/discovery/1.0`) currently 404 — checked
directly, and re-checked against the CDIF handbook's redirect target
(`cross-domain-interoperability-framework.github.io/cdifbook/`), which is an
introductory overview page, not a versioned conformance target. This does not
change the decision (§6.3) — only the pin mechanism: vendor specific artifacts
at a named commit SHA instead of a tag (§6.2), which satisfies the same
"stable now, move deliberately later" posture gema already applies to DataCite
4.6 vs. 4.7.

### 3.4 Why Croissant and CDIF DataStructure don't get merged or ranked

Verified in both projects' actual repositories: CDIF's DataStructure profile
(`profile-datastructure`) maps DDI-CDI concepts to schema.org
(`cdifTabularData`, `cdifLongData`, `cdifDataCube`); Croissant's model is
MLCommons' own `recordSet`/`field`. Neither repo references or maps to the
other — this is duplication, not composition, despite both being schema.org
JSON-LD (which is presumably what motivated CODATA's "Semantic Croissant"
naming). Decision: neither is the source of truth. The structure fetcher (§7)
produces one neutral, measured structure record; `recordSet` and
`cdifTabularData` are both thin serializations of that same record. This is
deferred until DataDescription work begins (§2) — noted here as the intended
shape, not built in v1.

## 4. Tech Stack & Project Structure

No new runtime dependencies. New/changed layout:

```
src/metadata_enricher/
  schemas/
    cdif/
      discovery/
        context.jsonld       — vendored CDIF-context-2026.jsonld
        frame.jsonld          — vendored CDIF-frame-2026.jsonld
        schema.json            — vendored CDIFDiscoverySchema.json
        shacl.ttl                — vendored discoveryRules.shacl
        VENDORED_SHA.txt          — the exact commit SHA these were pulled from
      cdif_discovery.py        — CDIFDiscoveryProfile: Schema Protocol impl
    datacite.py                 — DataCiteSchema46 (existing; becomes
                                   exporter-only, see §3.5 -- its Schema
                                   Protocol registration for direct LLM
                                   generation is removed)
    __init__.py                  — registers CDIFDiscoveryProfile as the sole
                                    generation-target Schema; DataCiteSchema46
                                    is no longer registered as one (§3.5)
  exporters/
    dataverse.py                 — existing, unchanged pattern
    datacite.py                  — NEW: MetadataDocument (CDIF-generated) ->
                                    DataCite 4.6 JSON, reusing DataCiteSchema46's
                                    normalization logic (§3.5), same crosswalk
                                    pattern as dataverse.py's docstring describes
    croissant.py                  — NEW: MetadataDocument -> Croissant JSON-LD
                                    (recordSet projection, §3.4)
  enrichers/
    structure_fetcher.py           — NEW: file/column structure enricher, §7
```

`config/agents.yaml`'s `fields:` lists move from DataCite field names to CDIF
Discovery field names (`schema:name`, `schema:subjectOf`, etc., with Pydantic
`Field(alias=...)` handling the CURIE-to-identifier mismatch). This is real
prompt-rewrite work, not a config-only change — flagged explicitly as the
actual cost of the flip, not hidden inside "just add a schema."

## 5. Schema Protocol: `CDIFDiscoveryProfile`

Implements the existing `Schema` Protocol (`schemas/base.py`) exactly like
`DataCiteSchema46` does — no Protocol changes needed; this is its documented
extension point.

- `name` → `"cdif-discovery"`, `version` → the vendored commit SHA (§6.2), not
  a semver, since CDIF has no releases to version against.
- `output_model` → a closed (`extra="forbid"`) Pydantic model covering CDIF
  Discovery's required floor (`@id`, `@type`, `@context`, `schema:name`,
  `schema:identifier`, `schema:dateModified`, `schema:subjectOf`) plus whatever
  additional Discovery properties gema's agents target. CURIE field names use
  `Field(alias="schema:name")` so the Python attribute stays a valid
  identifier.
- `validate_output` → standard Pydantic validation against the closed model;
  CDIF's own SHACL rules (`schemas/cdif/discovery/shacl.ttl`) run as an
  additional, non-blocking conformance check, not a substitute.
- `merge_agent_results`, `get_field_order`, `get_required_fields` → same
  responsibilities as `DataCiteSchema46`'s, retargeted to CDIF's field set.
- Serialization emits `dcterms:conformsTo: "https://w3id.org/cdif/discovery/1.0"`
  even though that URI currently 404s (§8, decided explicitly: emit anyway).

## 6. Validation, Determinism & Versioning

### 6.1 Determinism story, unchanged in kind

`cache.py`'s key already includes `response_model` — swapping the generation
target to `CDIFDiscoveryProfile.output_model` changes the key's content, not
its structure. Golden-fixture regression (`tests/fixtures/golden/`) gets a
**new fixture set** for CDIF-generated output; existing DataCite fixtures stay
meaningful only for as long as `DataCiteSchema46` is exercised directly (see
open item §9 on whether it stays a standalone generation path or exporter-only).

### 6.2 Vendoring policy (manual, maintainer-declared)

CDIF artifacts are vendored, not fetched live or tracked via a package
dependency. `schemas/cdif/discovery/VENDORED_SHA.txt` records the exact CDIF
repo commit SHA the four files were pulled from. **Re-syncing is manual and
maintainer-declared** — no automated drift detection, no scheduled bump. The
maintainer decides when to re-vendor (e.g. when CDIF eventually tags a real
release, or when a specific upstream change is known to matter), re-runs
`make record-golden` against the new artifacts, and reviews the fixture diff
before committing.

### 6.3 Why a SHA pin satisfies the stability requirement

CDIF has no tags (verified: zero releases across all relevant repos, commits
same-day as this investigation). A commit SHA is the standard pin mechanism for
an unreleased upstream and satisfies the same "stable now, move deliberately
later" posture gema already applies to DataCite versions — pin now, evolve on
purpose, never silently track a moving target.

## 7. Structure Fetcher (`enrichers/structure_fetcher.py`)

New enricher, sibling of `enrichers/content_fetcher.py`: same `enable_*` config
gate pattern (`enable_structure_fetch: bool = False` on `PipelineConfig`), same
never-raise, fail-soft contract as every other enricher.

**Scope:** the resource's own linked files. HTTP `HEAD` for size/MIME; for
tabular formats (CSV, Parquet, etc.), parse headers and infer column dtypes
from a bounded sample.

**Hard invariant, non-negotiable:** file and column structure is **measured,
never generated**. The LLM may describe a column it was shown in enrichment
context; it must never invent a `dataType` or column name that wasn't observed
in the fetched file. This is the same class of rule as the existing "unknown
MIME types are preserved unchanged, never nulled, never raised on" invariant in
`iana_normalizer.py`, and should be documented alongside it in
`enrichers/AGENTS.md` once implemented.

**Output:** one neutral, measured structure record (columns, dtypes, sizes,
MIME) — not a `recordSet` or `cdifTabularData` shape directly. Both of those
are later, separate ~200-line projection functions over this same record
(§3.4), built only once CDIF DataDescription work begins (§2, deferred).

**Ordering:** runs **upstream of generation** — CDIF DataDescription requires
knowing column facts before an agent can describe them, unlike today's
DataCite enrichment (ROR/ORCID/ISNI, content-fetch), which all run
**post-generation**, resolving or supplementing names the LLM already
produced. This is a genuine, asymmetric change to pipeline ordering:

```
Today (DataCite):            content_fetch -> generation -> identifier enrichment -> merge
Under CDIF (Discovery only):                  generation -> identifier enrichment -> merge
Under CDIF (+ DataDescription, future): structure_fetch -> generation -> identifier enrichment -> merge
```

Identifier enrichment's role does not shrink under CDIF — Discovery's required
floor includes `schema:identifier`, and its closed `$defs` shapes cover
`Identifier` and `Person.sameAs` — identifiers are structurally load-bearing in
CDIF's own schema, not decoration.

## 8. Conformance Assertion Despite a Dead Link

`CDIFDiscoveryProfile` emits `dcterms:conformsTo:
"https://w3id.org/cdif/discovery/1.0"` even though that URI currently returns
404 (verified directly, and via the CDIF handbook's own redirect target, which
does not resolve to a versioned conformance page either). Decision: **emit it
anyway.**

Rationale: this is what CDIF's own specification instructs implementers to
declare; omitting it makes gema's output non-conformant by CDIF's own stated
rule today, and the URI is expected to resolve once CDIF tags an actual
release. This is a known, temporary defect in CDIF's own infrastructure, not
gema's.

**Required, not optional:** this dead link must be noted clearly in both
places —
- **Code**: a comment directly above the `conformsTo` emission in
  `cdif_discovery.py` stating the URI is known-dead as of the vendored SHA's
  date, with a pointer to this section.
- **Docs**: `docs/CONFIGURATION.md` or this file's own changelog once
  implemented, so a future reader doesn't mistake a 404 for a gema bug.

Worth raising with CODATA directly as a low-cost, friendly finding.

## 9. Open Items / Future Work

- **A/B evaluation, demoted to diagnostic, not a gate.** CDIF conformance is a
  mandatory requirement regardless of measured output quality, so the
  A/B comparison (CDIF-generated → DataCite-exported vs. DataCite-generated
  directly, over the golden set) does not decide *whether* to ship — that's
  already decided. It exists to catch a specific, named implementation risk:
  LLM extraction quality may be sensitive to CDIF's field names
  (`schema:subjectOf`, `schema:dateModified`) being less represented in model
  training data than DataCite's (`titles`, `creators`). If the A/B shows a
  gap, the fix is prompt re-tuning, not reconsidering the pivot.
- **CDIF DataDescription profile** — deferred until the structure fetcher
  exists and has real usage data (§7). Also note CDIF's Provenance and Context
  profiles are marked "Under Development" upstream as of this writing — not
  targeted at all yet.
- **OpenAIRE** — no committed schema or date; named only as forward-looking
  evidence for the exporter-pattern requirement (§1), not a v1 deliverable.
- **Org-level self-hosted MCP deployment** — entirely outside this repo. Two
  operational findings worth relaying to whoever owns that deployment, not
  gema: `api/main.py` has a hardcoded access-token literal committed in
  source, and `/add_record`/`/rebuild` are unauthenticated by default — do not
  expose them publicly without adding auth at the deployment layer.
