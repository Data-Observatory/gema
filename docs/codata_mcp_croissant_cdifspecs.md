# CDIF/Croissant JSON-LD Pivot — Metadata Generation Architecture Specification

Status: v1 · drafted 2026-09-03 · **Implemented** (CDIF Discovery generation, DataCite/
Croissant/Dataverse exporters, SHACL check, JSON-LD framing, A/B diagnostic). The structure
fetcher (§7) and CDIF DataDescription remain deferred. This file is the single CDIF decision
record: the field mapping is Appendix A, every resolved open question is Appendix B (code
comments cite these by number, e.g. "Appendix B Q16").

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
than CDIF requires. The original draft proposed a fully closed (`extra="forbid"`)
model; **as implemented (Appendix B Q3)** the full-document model
`CDIFDiscoveryOutputModel` is `extra="allow"` plus a `model_validator(mode="after")`
that hard-enforces the required floor and both conditional OR-groups. Generation
is still constrained per agent: each agent decodes against a per-agent model
built by `CDIFDiscoveryProfile.build_output_model(fields)` covering only that
agent's declared fields (also `extra="allow"`), so Instructor still type-validates
every targeted field. CDIF's
SHACL rules (vendored `shacl.ttl`) run as an optional, non-blocking outer check
(`PipelineConfig.validate_shacl_conformance`, default off).

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

New runtime dependencies: `pyshacl`, `rdflib`, `pyld` (for the SHACL check and
JSON-LD framing, Appendix B Q5; `pyld` ships no type stubs and has a mypy
`ignore_missing_imports` override). Layout as built:

```
src/metadata_enricher/
  schemas/
    cdif/
      discovery/
        frame.jsonld          — vendored CDIFDiscovery-frame.jsonld
        schema.json            — vendored CDIFDiscoveryProfileStructuredSchema.json
        shacl.ttl                — vendored discoveryRules.shacl
        crosswalk.xlsx           — vendored CDIF-metadata-crosswalks-merged.xlsx
                                    (DataCite<->schema.org crosswalk, reference
                                    only, read by no code; source for Appendix A)
        VENDORED_SHA.txt          — the exact commit SHA these were pulled from
        cdif_discovery.py        — CDIFDiscoveryProfile: Schema Protocol impl
    (no context.jsonld — none exists upstream; @context is embedded in
     schema.json and frame.jsonld)
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
                                    (top-level Dataset fields only; recordSet
                                    deferred with the structure fetcher, §3.4)
  enrichers/
    structure_fetcher.py           — NOT BUILT, deferred (§7, Appendix B Q10-Q12)
```

Both new exporters are reachable from the CLI via `gema process --export
{datacite,croissant}` (repeatable, requires `--output`; each export is written
as a sibling file and a failing export never blocks the primary output).

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
- `output_model` → `CDIFDiscoveryOutputModel`, an **open** (`extra="allow"`)
  Pydantic model covering CDIF Discovery's required floor (`@id`, `@type`,
  `@context`, `schema:name`, `schema:identifier`, `schema:dateModified`,
  `schema:subjectOf`) plus the Discovery properties gema's agents target, with a
  `model_validator(mode="after")` enforcing the floor and the two conditional
  groups (`schema:license` OR `schema:conditionsOfAccess`; `schema:url` OR
  `schema:distribution`) — Appendix B Q3. CURIE field names use
  `Field(alias="schema:name")` so the Python attribute stays a valid
  identifier. `build_output_model(fields)` derives a per-agent subset model
  (reasoning first, then the agent's fields in declared order; its class name
  is a digest of field names *and* type annotations, so it is part of the LLM
  cache key).
- `validate_output` → Pydantic validation against `CDIFDiscoveryOutputModel`.
  Not called by the live pipeline (tests only). CDIF's own SHACL rules run
  separately via `check_shacl_conformance(doc)` — wired into `pipeline.py` as an
  opt-in, non-blocking post-merge step (`validate_shacl_conformance`, default
  `False`; findings become warnings, never errors). `frame_output(doc)` (pyld
  framing against `frame.jsonld`) exists but has no caller yet.
- `merge_agent_results`, `get_field_order`, `get_required_fields` → same
  responsibilities as `DataCiteSchema46`'s, retargeted to CDIF's field set.
  `merge_agent_results` also does the JSON-LD serialization steps: wraps
  `schema:creator` in `{"@list": [...]}` (C4), collapses top-level
  `schema:identifier` to a singular value (Q23), renders
  `dcterms:bibliographicCitation` to a literal string (Q21), and injects the
  envelope (`@context`, `@id`, `@type`, `schema:dateModified`,
  `schema:subjectOf`).
- The envelope emits **both** `https://w3id.org/cdif/core/1.0` and
  `https://w3id.org/cdif/discovery/1.0` (core first) as
  `schema:subjectOf.dcterms:conformsTo`, as required by the vendored SHACL
  `metadataProfileProperty` shape (Appendix B Q18), even though both URIs
  currently 404 (§8, decided explicitly: emit anyway).

## 6. Validation, Determinism & Versioning

### 6.1 Determinism story, unchanged in kind

`cache.py`'s key already includes `response_model` — swapping the generation
target to `CDIFDiscoveryProfile.output_model` changes the key's content, not
its structure. Golden-fixture regression (`tests/fixtures/golden/`) gets a
**new fixture set** for CDIF-generated output (done: `tests/fixtures/golden/`
fully replaced, Appendix B Q7). `DataCiteSchema46` became exporter-only (§3.5),
so the pre-pivot DataCite fixtures survive only as a frozen baseline at
`tests/fixtures/golden_datacite46_baseline/` (with `config/legacy/agents_datacite46.yaml`)
for the A/B diagnostic (§9).

### 6.2 Vendoring policy (manual, maintainer-declared)

CDIF artifacts are vendored, not fetched live or tracked via a package
dependency. `schemas/cdif/discovery/VENDORED_SHA.txt` records the exact CDIF
repo commit SHA the four files (`schema.json`, `frame.jsonld`, `shacl.ttl`,
`crosswalk.xlsx`) were pulled from. **Re-syncing is manual and
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

**Status: deferred, not built** (Appendix B Q10-Q12). No consumer exists yet
(`ResourceDescription` has no structure field; `agents/base.py`'s resource dict
has a fixed key set). Picking it up also needs `ResourceDescription` and the
agent resource dict extended, `PipelineConfig.enable_structure_fetch`, a
`_maybe_fetch_structure()` step mirroring `_maybe_fetch_content()`, and a
"measured, never generated" test that targets LLM *output* (generated columns ⊆
measured columns), not only the fetcher's input handling. The design below is
the intended shape.

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
Pre-pivot (DataCite):        content_fetch -> generation -> merge -> identifier enrichment
As built (CDIF Discovery):   content_fetch -> generation -> merge -> deterministic fallbacks
                               -> DOI resolution -> identifier enrichment -> PID validation
                               -> SHACL check (opt-in)
Future (+ DataDescription):  content_fetch -> structure_fetch -> generation -> merge -> ...
```

`content_fetch` (`pipeline.py::_maybe_fetch_content`, `enable_content_fetch`,
on in `config/agents.yaml`) runs before generation in every variant: agents
read `resource.fetched_content` while building their prompt. It is skipped when
the input already carries `fetched_content`. Where structure_fetch sits relative
to content_fetch is still open (Appendix B Q11).

Identifier enrichment's role does not shrink under CDIF — Discovery's required
floor includes `schema:identifier`, and its closed `$defs` shapes cover
`Identifier` and `Person.sameAs` — identifiers are structurally load-bearing in
CDIF's own schema, not decoration.

## 8. Conformance Assertion Despite a Dead Link

`CDIFDiscoveryProfile` emits `dcterms:conformsTo` with both
`"https://w3id.org/cdif/core/1.0"` and `"https://w3id.org/cdif/discovery/1.0"`
(the core URI was added later, Appendix B Q18) even though these URIs currently
return 404 (verified directly, and via the CDIF handbook's own redirect target,
which does not resolve to a versioned conformance page either). Decision: **emit
them anyway.**

Rationale: this is what CDIF's own specification instructs implementers to
declare; omitting it makes gema's output non-conformant by CDIF's own stated
rule today, and the URI is expected to resolve once CDIF tags an actual
release. This is a known, temporary defect in CDIF's own infrastructure, not
gema's.

**Required, not optional:** this dead link must be noted clearly in both
places —
- **Code**: a comment directly above the `conformsTo` emission in
  `cdif_discovery.py::_inject_envelope` stating the URIs are known-dead as of
  the vendored SHA's date, with a pointer to this section (present).
- **Docs**: this section is the docs-side record, so a future reader doesn't
  mistake a 404 for a gema bug.

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
  **Done**: `scripts/ab_eval_cdif_vs_datacite.py` (`make ab-eval`, manual, not
  CI-gating). Side A cache-replays the current pipeline over the golden inputs
  and crosswalks through `exporters/datacite.py`; side B is the frozen
  `tests/fixtures/golden_datacite46_baseline/expected/` (not re-run). Scored
  per resource and per field with `json_semantic_diff`. LLM calls are
  cache-replayed but ROR/ISNI/ORCID/doi.org lookups still hit the network.
  Treat overall scores as informational: the baseline predates Appendix B
  Q16-Q23's intentional shape changes, so overall scores sit far below 0.85 by
  design (0.00-0.32 on 2026-09-06). The useful signal is per-field: no field
  went silently empty.
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

---

## Appendix A — DataCite → CDIF field mapping

The per-field mapping used to rewrite `config/agents.yaml` for CDIF and, read in
reverse, to build `exporters/datacite.py`. Verified against the vendored
`schema.json`, CDIF's own `crosswalk.xlsx` (150-row DataCite↔schema.org
crosswalk, used as the authority wherever it has an answer), the CDIF
Implementation Guide, the schema.org vocabulary, and DCMI Terms. One row per
pre-pivot DataCite field (`schemas/datacite.py` shapes).

The vendored schema declares 32 top-level properties: 27 in `.properties` plus 5
in `.allOf[3].properties` (`schema:measurementTechnique`,
`schema:variableMeasured`, `schema:spatialCoverage`, `schema:temporalCoverage`,
`dqv:hasQualityMeasurement`). Those 5 are first-class Discovery properties, not
a `profile-discovery` extension. Required floor (`allOf[0].required`): `@id,
@type, @context, schema:name, schema:identifier, schema:dateModified,
schema:subjectOf`. Conditional groups: `allOf[1]` = `schema:license` OR
`schema:conditionsOfAccess`; `allOf[2]` = `schema:url` OR `schema:distribution`.

**Dropped from CDIF v1 scope** (no clean CDIF home or no source signal):
`temporal_events` (frequency), `media_files[].Collections`, and
`publishing_principles`. Their rows below are kept as the intended target if
they are ever reinstated. The DataCite exporter keeps the `"Collections"`
capitalization for legacy compatibility.

| DataCite field | CDIF/JSON-LD target | Confidence |
|---|---|---|
| `resource.identifier`/`identifier_type` | `@id` (if resolvable URI) else `schema:identifier` (PropertyValue: `schema:propertyID`←type, `schema:value`, `schema:url`); singular at top level (Q23) | Verified |
| `resource.resource_type_general` | `@type` (array incl. `schema:Dataset`) | Verified |
| `resource.resource_type` | `schema:additionalType` | Verified |
| `resource.version` | `schema:version` | Verified |
| `resource.language` | `schema:inLanguage` | Verified |
| `resource.publication_year` | `schema:datePublished` | Verified |
| `resource.editor` | `schema:contributor` → Role `roleName:"Editor"` (Q17 shape) | Verified |
| `resource.maintainer` | `schema:maintainer` (Person/Org), distinct from `subjectOf.maintainer` (metadata-record contact) | Verified term, inferred node |
| `resource.contact` | `schema:contributor` → Role `roleName:"ContactPerson"` | Verified |
| `resource.producer` | `schema:producer` | Verified |
| `resource.thumbnail` | `schema:relatedLink` → `LinkRole{linkRelationship:"thumbnail"}` | Verified |
| `titles` (main) | `schema:name`, single-valued (C1) | Verified |
| `titles` (Alternative/Subtitle/Translated/Other) | `schema:alternateName` | Verified |
| `descriptions` (Abstract) | `schema:description`, single-valued (C1) | Verified |
| `descriptions` (Methods) | `schema:measurementTechnique` | Inference (good fit) |
| `descriptions` (other types) | fold into `schema:description`, or `dcterms:tableOfContents`/`schema:isPartOf` | Inference |
| `languages` | `schema:inLanguage` (first) + `dcterms:language` (overflow), C2 | Verified constraint |
| `dates[Created]` | `schema:dateCreated` | Verified |
| `dates[Updated]` | `schema:dateModified` (required floor; currently injected as processing date, see BACKLOG O-1) | Verified |
| `dates[Issued]` | `schema:datePublished` | Verified |
| `dates[Copyrighted]` | `schema:copyrightYear` | Verified |
| `dates[Available]` (embargo) | `schema:conditionsOfAccess` | Verified |
| `dates[Collected]` | `schema:temporalCoverage` | Verified |
| `dates[Accepted/Submitted/Valid/Withdrawn]` | `dcterms:dateAccepted`/`dateSubmitted`/`valid`/`schema:expires` | Inference per term |
| `alternate_identifiers` | `schema:sameAs`: identity assertions, `minItems: 1` (C6) | Verified |
| `related_identifiers` | `schema:relatedLink` → `LinkRole{linkRelationship←relation_type, target: EntryPoint}`; typed relations, never merged with `sameAs` | Verified |
| `related_identifiers[IsDerivedFrom]` | `prov:wasDerivedFrom` (CDIF says this, not `schema:isBasedOn`) | Verified |
| `related_identifiers[HasPart/IsPartOf]` | `schema:hasPart`/`schema:isPartOf` | Verified/flagged |
| `geo_locations` | `schema:spatialCoverage[]` → `Place{name, identifier, geo: GeoCoordinates\|GeoShape}` | Verified |
| `temporal_events` (frequency) — *dropped from v1* | `dcterms:accrualPeriodicity`, not `schema:repeatFrequency` (domain is `Schedule` only, though CDIF's crosswalk suggests it) | Inference, flagged |
| `subjects` | `schema:keywords[]` as `DefinedTerm{name, inDefinedTermSet, identifier, termCode}` | Verified |
| `categories` | `schema:about[]` (DefinedTerm). Judgment call: CDIF's crosswalk says `keywords`, but `about` is semantically cleaner. Low-stakes, reversible | Flagged |
| `audiences` | `schema:audience`→`Audience{audienceType}` + `schema:educationalLevel` + `dcterms:mediator` + `dcterms:instructionalMethod` (verbatim DCMI lift; keeps all 4 sub-fields instead of folding into keywords) | Verified |
| `creators` | `schema:creator` → `{"@list":[Person\|Organization]}`, an object wrapping `@list`, not a bare array (C4) | Verified |
| `creators[].contributor_type` | `schema:contributor` → `{"@type":["schema:Role"], "schema:roleName", "schema:contributor": <Person\|Organization>}`: the actor nests inside the Role (Q17) | Verified |
| `publishers` | `schema:publisher` (single) + overflow → `schema:provider[]` (C3) | Verified constraint |
| `rights.rights`/`rights_uri`/`rights_identifier` | `schema:license[]` (string\|`{@id}`\|`LabeledLink`) | Verified |
| `rights.rights_condition` | `schema:conditionsOfAccess` | Verified |
| `rights.rights_holder` | `schema:copyrightHolder` | Verified |
| `funding_references` | `schema:funding[]` → `MonetaryGrant{name, identifier, funder: Organization}`; funder nests inside the grant, no top-level `schema:funder` | Verified |
| `citations` | `dcterms:bibliographicCitation[]` as literal strings (Q19, Q21). **Not** `schema:citation` (forbidden by vendored SHACL `cdifd:citationProperty`, `sh:maxCount 0`), not `prov:wasDerivedFrom` (input lineage, a different concept) | Corrected |
| `media_files` (file access) | `schema:distribution[]` → `DataDownload{contentUrl, encodingFormat, contentSize, spdx:checksum}` | Verified |
| `media_files[].variable_measured` | `schema:variableMeasured[]` → `PropertyValue` | Verified |
| `media_files[].measurement_technique` | `schema:measurementTechnique` (on export: wins over `descriptions[Methods]` when a usable distribution exists; Methods is only the fallback) | Verified |
| `media_files[].data_quality` | `dqv:hasQualityMeasurement` (needs `dqv` prefix) | Verified |
| `media_files[].provenance` | `prov:wasGeneratedBy` → `Activity{used:[...]}` | Verified |
| `media_files[].temporal_resolution` | `dcat:temporalResolution` | Verified |
| `media_files[].Collections` — *dropped from v1* | `schema:includedInDataCatalog` → `DataCatalog` | Verified |
| `media_files[].physical_carrier` | drop (always literal `"digital"`) | Verified |

### Hard JSON-Schema constraints

Found by parsing the vendored schema's actual types. Missing these produces
invalid documents silently:

- **C1**: `schema:name`/`schema:description` are single-valued `string`. Primary
  value wins; the rest go to `alternateName` or are folded. No language-tagged
  `{"@value","@language"}` objects (legal RDF, fails this JSON Schema).
- **C2**: `schema:inLanguage` is a single `string`. Overflow → `dcterms:language`.
- **C3**: `schema:publisher` is a single object; extra publishers →
  `schema:provider` (an array).
- **C4**: `schema:creator` is an object wrapping `@list` (order-preserving), not
  a bare array, unlike `schema:contributor`, which is a bare array. Agents emit a
  plain list; `merge_agent_results` wraps it once. Readers go through
  `types.jsonld_list_unwrap()`.
- **C5**: `@context` requires `schema, dcterms, dcat, prov`. Richer forms need
  `spdx` (checksums), `geosparql`+`sf` (geometry), `time` (intervals), `dqv`
  (quality), some with `const`-pinned URIs in `allOf[3]` that must be emitted
  verbatim.
- **C6**: `schema:sameAs` has `minItems: 1`. Omit the key when empty, never `[]`
  (the same "absent, not empty" rule applies to nested `schema:identifier`).
- **C7**: nested `@type` values are arrays with a `contains` const (e.g.
  `["schema:Place"]`), not bare strings. Read through `types.first_type_label()`.
- **Nested keys are CURIEs** (`schema:name`, `schema:propertyID`, ...), not bare
  English keys. JSON-LD tooling drops a key that has no `@context` term during
  expansion, so the old bare-key shape silently lost creator names and DOIs
  in RDF. Deliberate gema extensions: `schema:givenName`/`schema:familyName`/
  `schema:email` on actors (real schema.org terms the profile doesn't reference).
  Bare on purpose: `matched_via`/`confidence`/`status` inside an identifier
  entry (enrichment audit trail, outside the JSON-LD graph). These also stay bare
  because there is no vendored CURIE to map them to: `schema:audience`
  sub-keys, `schema:conditionsOfAccess`'s `condition`/`date`, and
  `schema:distribution`'s `checksum`/`temporal_resolution`/`contentSize`
  `{size, unit}`.

---

## Appendix B — Decision log

Resolutions of the pivot's open questions, keeping their original numbers
(code comments cite them, e.g. "Appendix B Q16"). Still-open owner questions
(O-1..O-3) and deferred work live in `BACKLOG.md`.

### Q1 — CDIF vendoring source

`Cross-Domain-Interoperability-Framework/doc-corediscovery` at
`81c28260778426cc61302105fc7191b4db360bc9` (2026-05-16): the composite
discovery application profile, not the narrower `profile-discovery` module.
Vendored: `schema.json`, `frame.jsonld`, `shacl.ttl`, `crosswalk.xlsx`. No
standalone `context.jsonld` exists upstream. Pin recorded in `VENDORED_SHA.txt`.

### Q2 — Field coverage beyond the required floor

Full per-field mapping over all 32 declared properties: Appendix A.

### Q3 — `extra="forbid"` vs `"allow"` on `output_model`

`extra="allow"`, plus a `model_validator(mode="after")` that hard-enforces the
required floor and both conditional groups. It raises when the floor is not
met and lets everything else through. Per-agent models from
`build_output_model()` do not inherit the floor validator, since each agent
produces only a subset.

### Q4 — Where the JSON-LD envelope is emitted

Inside `CDIFDiscoveryProfile.merge_agent_results` (`_inject_envelope`). Agents
never generate `@context`/`@id`/`@type`/`schema:dateModified`/`schema:subjectOf`.

### Q5 — Execute SHACL and JSON-LD framing in v1?

Yes. `pyshacl`, `rdflib`, `pyld` added as runtime deps.
`check_shacl_conformance(doc)` serializes to JSON-LD, parses with rdflib, then
runs `pyshacl.validate(..., advanced=True)`. `advanced=True` is required
because some vendored shapes use `sh:SPARQLTarget`. It never raises (an
infrastructure failure logs and returns `[]`) and returns one readable string
per `sh:ValidationResult` of **any** severity (`sh:Info`/`sh:Warning` included,
no severity label). Wired into `pipeline.py` as an opt-in, non-blocking step
(`validate_shacl_conformance`, default `False`), because every real golden
fixture produced findings, many outside gema's control. `frame_output()`
exists but has no caller.

### Q6 — Enrichment architecture fork

Option (A): `identifier_enricher.py`, `doi_resolver.py`, `pid_validator.py`,
`output.py`, `exporters/dataverse.py` read CDIF field names directly off the
CDIF-generated `MetadataDocument`. No DataCite-shaped intermediate
representation.

### Q7 — Golden fixture strategy

Full replace of `tests/fixtures/golden/` with CDIF output, plus a frozen
pre-pivot snapshot (`tests/fixtures/golden_datacite46_baseline/`,
`config/legacy/agents_datacite46.yaml`) for the A/B diagnostic.

### Q8 — DataCite export LLM-call scope

None. `exporters/datacite.py::to_datacite_json` is a pure crosswalk;
`token_usage` is always zero and is kept only for shape parity with the
Dataverse exporter. `DataCiteSchema46`'s normalizers/`validate_output` are
reused as the last step (never copied), via a module-level singleton
(`_get_datacite_schema()`) so the ~505KB IANA MIME snapshot isn't re-parsed
per export.

### Q9 — Croissant top-level field mapping

Verified against `docs/croissant-spec-1.1.md` in `mlcommons/croissant` @
`0e5dcb796dba285b396011638a68909c78a39664` (fetched 2026-09-04). Required:
`@context, @type ("sc:Dataset"), dct:conformsTo, name, description, license,
url, creator, datePublished, distribution` (`distribution` is required, not
optional: Croissant "makes it required"). Recommended: `keywords, publisher,
version, dateCreated, dateModified, sameAs, sdLicense, inLanguage`. Optional:
`citeAs, isLiveDataset, sdVersion`. Not mapped in v1 (no CDIF source):
`sdLicense, citeAs, isLiveDataset, sdVersion`. `recordSet` is omitted entirely.
That conforms to the spec, because `recordSet` is optional there; it is
blocked on the structure fetcher, not a defect.

### Q10 — Structure fetcher format list / sample strategy

Deferred with the whole feature (§7, BACKLOG).

### Q11 — Content-fetch vs structure-fetch ordering

Deferred with the whole feature (§7, BACKLOG).

### Q12 — Does the structure fetcher ship in v1?

No. Nothing would consume it yet (see §7), so building it now would be dead
code. It stays tracked in BACKLOG.

### Q13 — Where DataCite vocab / affiliation tables live after the rewrite

They stay in `config/agents.yaml`'s CDIF-facing prompts: SPDX/CC license
priority, ANID/FONDECYT funding taxonomy, the Chilean ministry hierarchy table.
They encode domain knowledge for reading Spanish source text, not DataCite
shape, so nothing moves to `exporters/datacite.py`.

### Q14 — `visor/session_settings.py` persisted-override migration

Not a gap. `visor/settings.py::apply_agent_overrides` already skips an override
whose agent ID or provider no longer exists, and IDs/providers didn't change in
the pivot.

### Q15 — `config/migrate.py`'s hardcoded schema name

Keep `"datacite-4.6"` (migrated legacy configs are DataCite-shaped by
definition), plus a `logger.warning` and docstring note that it is no longer a
registered generation schema.

### Q16 — Nested `schema:identifier` cardinality

The vendored `$defs` make `schema:identifier` singular on Person/Organization/
MonetaryGrant; gema used to write a list. Resolved: one singular
`schema:identifier` (preferred match first, per `_SCHEME_ORDER`) plus
`schema:sameAs` overflow for any extra match, at every nesting level
`identifier_enricher.py` writes (creator, affiliation, publisher, funder).
Write path: `identifier_enricher._write_identifiers()`. Shared read path:
`types.entity_identifiers()` (singular + overflow, preferred first), used by
every exporter. An empty placeholder (`[]`/`{}`) is removed
(`_strip_empty_identifier()`, and omitted in `doi_resolver.py`'s backfill),
following "absent, not empty". The rationale is never to drop a resolved
identifier, while matching CDIF's singular-plus-sameAs pattern (same shape as
C3).

### Q17 — `schema:contributor`'s Role wrapper

Restructured to the vendored shape exactly:
`{"@type":["schema:Role"], "schema:roleName": ..., "schema:contributor": <actor>}`.
Only `creators_publishers` produces role-carrying contributors. Exporters split
an entry via `exporters/datacite.py::_role_and_actor()` and
`exporters/dataverse.py::_build_dataset_contact`. Both detect the wrapper
by **key presence** (`schema:contributor`/`schema:roleName`), not by an exact
`@type` match, so an LLM slip on `@type` doesn't make the entry vanish. A bare
role-less actor is still valid and handled. Known simplification: the nested
actor's `@type` defaults to `schema:Organization`, because the prompt doesn't
classify contributors as Person vs Organization. No consumer branches on it
today.

### Q18 — `dcterms:conformsTo` missing the core URI

`_inject_envelope` emits both `https://w3id.org/cdif/core/1.0` and
`https://w3id.org/cdif/discovery/1.0` (core first), matching
`cdifd:metadataProfileProperty`'s two `sh:hasValue` constraints. Both URIs are
known-dead as of the vendored SHA date (§8).

### Q19 — `schema:citation` forbidden by SHACL

The vendored `cdifd:citationProperty` (`sh:maxCount 0`, `sh:Info` severity)
says to use `dcterms:bibliographicCitation` or `schema:relatedLink`. The
original mapping table had wrongly marked `schema:citation[]` as verified.
Retargeted throughout: `CDIFDiscoveryOutputModel.dcterms_bibliographic_citation`
(was `schema_citation`), the `rights_funding_citations` agent's `fields:` and
prompt, `exporters/datacite.py::_build_citations`, and golden fixtures. Shape:
see Q21.

### Q20 — `schema:url` unreachable from real output

No agent produces `schema:url`, so the `url|distribution` group could only be
met via distribution. Resolved in `pipeline.py::_process_resource`: after
`merger.merge()`, set `schema:url` from `resource.url` only when no agent
produced one, the input URL is non-empty, **and** it is a real `http(s)://` URL.
`resource.url` can be a bare DOI (e.g. `sample_input06`), and writing that raw
would pre-empt the exporters' own DOI→`https://doi.org/` resolution. This is
deliberately the *input* URL, not a verified landing page. It lives in
`pipeline.py` because the Schema Protocol has no access to
`ResourceDescription`. Practical effect: exporters and the SHACL
`accessProperty` shape. No runtime validation gate calls `validate_output()`.

### Q21 — Structured `dcterms:bibliographicCitation` loses all data in JSON-LD

The structured sub-keys (`title`, `volume`, ...) have no `@context` term, so
expansion drops them all. DCMI also defines the term with `rdfs:range
rdfs:Literal`. Resolved: render a plain literal string deterministically in
code (`CDIFDiscoveryProfile._format_bibliographic_citation`, called from
`merge_agent_results`). The LLM still emits the structured dict, which is
easier to extract. The field annotation was widened to
`list[dict[str, Any] | str]` so `validate_output()` accepts a merged document.
Rejected for v1: a nested `schema:isPartOf`/`PublicationVolume`/
`PublicationIssue` breakdown, which would be extra work with no consumer.

### Q22 — Nested `schema:sameAs` overflow shape off-spec

The vendored `$defs/Person`/`$defs/Organization` type `schema:sameAs` as
`string | {@id}`, not `Identifier`. Overflow entries are now a bare
`{"@id": <resolvable URL>}`. Provenance is dropped there with nothing lost,
since it is identical to the sibling primary entry's (checked against every
real occurrence). `types.entity_identifiers()` reverse-parses the scheme from
the URL host (`ror.org`/`isni.org`/`orcid.org`). An unknown host degrades to
`{"schema:url": url}`, and legacy full-PropertyValue entries are still
accepted. Fixed alongside: ISNI URLs use the canonical `https://isni.org/isni/<id>`
form, which matters because the URL is now an overflow entry's only record.

### Q23 — Document-level `schema:identifier` cardinality

The top-level `properties.schema:identifier` is also singular
(`anyOf: [Identifier, string]`). `merge_agent_results` collapses the agent's
(normally one-entry) list to a singular dict, overflowing any extras into
`schema:sameAs` as `{"@id": ...}`, and omits the key when empty. The output
model's annotation stays `list[dict[str, Any]]` (no cache impact): a
`mode="before"` validator wraps a singular dict for `validate_output()`.
Readers (`doi_resolver.py::_doi_identifier`, `exporters/dataverse.py`,
`output.py`) accept the singular shape and still tolerate a list.

### Cache-key migration rule (learned from Q17/Q19/Q21)

The LLM response cache key changes when an agent's prompt text, its `fields:`
list, **or any field's type annotation** changes. The
`build_output_model` digest hashes each field's `repr(annotation)`, and some
agents also fold `tools` into the key. Whenever the extracted facts themselves
are unchanged, migrate committed `tests/fixtures/golden/cache/` entries
mechanically: read the old entry with pre-edit code, transform it if needed,
then write it under the post-edit key. This avoids a live `make record-golden`.

### B2 — Production model: stay on `deepseek-v4-flash`

The 2026-09-06 model-swap experiment over the 18-item do_catalog corpus scored
`omen-alpha` highest on both structural (0.507 vs baseline 0.471) and GEval
judge (0.489 vs 0.456), with `longcat-2.0` in between. Both were 3-10x+ slower
per item, and `gpt-5.6-luna` failed 0/6 on provider 500s. **Owner decision:
declined. `deepseek-v4-flash` stays the production default**, per the standing
instruction that deepseek remains default while gema stays able to run any
model. The numbers are kept for reference.

### A0 — CODATA `semantic-croissant` code: hard stop

`github.com/codata/semantic-croissant` has **no license**: `license: null`, and
no LICENSE/COPYING/SPDX tag or header anywhere. Under default copyright that
grants no right to copy or vendor it. Even setting the license aside, its
HTML→markdown step is just `markdownify`. The A1 bake-off of trafilatura,
markdownify and html2text against gema's `clean_html_to_text` on the 6 golden
URLs showed a real format win on only 1/6 pages. Three of the 6 were
JS-rendered SPAs and one was dead. **No markdown migration (Phase A2+ not
started).** The JS-rendering gap was later addressed differently: the opt-in
`enable_js_render_fallback` uses the Apache-2.0 `obscura` CLI, bundled into
Visor at build time, with `clean_html_to_text` still deciding what counts as
content. CODATA's JSON-LD/Croissant generation machinery is also not adopted:
it would duplicate gema's native generation and risks breaking the "structure
is measured, never generated" invariant.

### O-4 — Normalize `resource.publisher` in the actor fallback?

Yes, narrowly. The deterministic fallback cascade in `pipeline.py` fills only
empty slots: `resource.publisher` → `schema:publisher` → `schema:creator` →
`schema:copyrightHolder`, plus the "Datos Abiertos del Estado de Chile" license
→ `copyrightHolder: "Estado de Chile"` rule. Before copying, it strips the two
known trailing suffixes (`" - Gobierno de Chile"`, `" (Chile)"`), which the
system prompt forbids elsewhere. Extend the list if more suffix forms appear.

### O-5 — `sample_input05`'s golden publisher

It was a real bug, not a curation choice. ROR's `?affiliation=` service
"chose" a Madrid facility (`ror.org/04q93ds34`) for Chile's ODEPA at
`confidence: 1.0`. Fix: `identifier_resolver.py::_try_ror_affiliation` now
cross-checks the chosen candidate's country against the resource's country
hint. A known mismatch is demoted to `confidence=0.5, status="review"`, which the
existing auto-attach gate refuses. It does not override ROR's `chosen`, and an
org with unknown country is not penalized. A later live re-record produced an
ISNI-only, no-ROR match for ODEPA, confirming the fix.

### O-6 — Is vendoring CODATA's code on the table?

No. See A0: the repo is unlicensed, which decides it regardless of gema's own
license.
