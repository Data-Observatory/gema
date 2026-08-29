# enrichers/

Post-merge enrichment modules. Deterministic transforms applied to `MetadataDocument` after the LLM agent pipeline.

## STRUCTURE

```
enrichers/
├── __init__.py                  # Exports IdentifierEnricher, IdentifierResolver, IdentifierMatch, fetch_page_content
├── content_fetcher.py           # Best-effort live URL fetch -> cleaned text for ResourceDescription.fetched_content (pre-orchestration, opt-in)
├── iana_normalizer.py           # MIME type normalization against IANA registry (standalone, not wired)
├── country_extractor.py         # ISO country code extraction from HTML/URL — wired into both
│                                 #   agent prompts (agents/base.py) and ROR/ISNI matching (pipeline.py -> IdentifierEnricher)
├── identifier_types.py          # IdentifierMatch pydantic model (resolved org/person identifier)
├── identifier_overrides.py      # Human-curated ROR/ISNI override store (config/overrides.yaml), checked before any network call
├── ror_client.py                # ROR API v2 client (affiliation + query endpoints), extract_country/extract_isni/extract_parent
├── isni_client.py                # ISNI SRU client (XML parsing via httpx + ElementTree)
├── orcid_client.py               # ORCID Public API v3.0 client (OAuth client_credentials + person search)
├── fuzzy_matcher.py             # rapidfuzz WRatio org name matching, normalization (accent folding, Spanish abbreviations), country-hint re-rank
├── identifier_resolver.py       # resolve() merges ROR+ISNI; resolve_person() for ORCID
├── identifier_enricher.py       # Post-merge document enrichment (creators, publishers, funding) + match provenance
├── crossref_client.py            # Crossref public Works API client (GET /works/{doi})
├── doi_resolver.py               # Post-merge DOI backfill (titles, creators, publisher, Issued date)
└── pid_validator.py             # Format + live-resolution checks for DOI/ROR/ISNI (shared by Pipeline + scripts/validate_real_output.py)
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Enable auto content-fetch (populate `fetched_content` from `resource.url`) | `PipelineConfig.enable_content_fetch = True` (config/models.py); wired in `pipeline.py:Pipeline._maybe_fetch_content` |
| Enable identifier enrichment | `PipelineConfig.enable_identifier_enrichment = True` (config/models.py) |
| Add/edit a human-curated ROR/ISNI override | `config/overrides.yaml` — see `identifier_overrides.py`; path set via `PipelineConfig.identifier_overrides_path` |
| Enable DOI resolution (Crossref backfill) | `PipelineConfig.enable_doi_resolution = True` (config/models.py) |
| Change what DOI resolution backfills | `DOIResolverEnricher._backfill_*()` (doi_resolver.py) — currently titles, creators, publishers, Issued date |
| Enable/disable automatic PID validation | `PipelineConfig.validate_pids` / `.validate_pids_live` (config/models.py) — on by default |
| Change org resolution order/merge | `IdentifierResolver._try_resolve()` / `_merge_org_matches()` (identifier_resolver.py) |
| Change ORCID ambiguity policy | `IdentifierResolver._try_orcid()` — currently: >1 hit → `status="review"`, not auto-attached |
| Change fuzzy threshold | `IdentifierResolver.__init__(fuzzy_threshold=90.0)` |
| Change cache TTL / dir | `IdentifierResolver.__init__(cache_ttl=..., cache_dir=...)` |
| Add new identifier field to write | `IdentifierEnricher._enrich_*()` methods |
| Add a new PID scheme to validate | `pid_validator.py` — `validate_pid_format()` / `resolve_pid()` / `_KNOWN_SCHEMES` |

## IDENTIFIER RESOLUTION ARCHITECTURE

```
Organization name → IdentifierResolver.resolve(name, country=None)
                       │
                       ├── 0. Check IdentifierOverrides (config/overrides.yaml), if configured
                       │      Hit? → return immediately, no cache write, no network call
                       │
                       ├── 1. Check diskcache (~/.cache/gema/identifiers/, 30-day TTL,
                       │      key includes normalized name + country)
                       │      Hit? → return cached IdentifierMatch or None (negative cache)
                       │
                       ├── 2. ROR ?affiliation=, else ?query= + rapidfuzz WRatio (threshold 90).
                       │      *country* re-ranks ?query= candidates (soft hint, never a hard
                       │      filter — see fuzzy_matcher.match_organization's country_hint)
                       ├── 3. ROR match found, has its own linked ISNI, AND status=="auto"?
                       │      → return it as-is, SKIP the independent ISNI check below —
                       │      that check can only ever demote confidence/status, never
                       │      confirm it, so it's pure noise in that case. An ambiguous
                       │      ("review") ROR match still runs the ISNI check, since it
                       │      stays "review" either way and the extra data point is free.
                       ├── 4. Otherwise: ISNI SRU pica.nw + rapidfuzz WRatio
                       │
                       ├── Both found? → merge into ONE IdentifierMatch carrying both
                       │      ror_id and isni_id (ROR's own linked ISNI, if present,
                       │      always wins over an independently fuzzy-matched one)
                       │
                       └── Cache result (positive or negative) → return

Person (given_name, family_name[, affiliation]) → IdentifierResolver.resolve_person(...)
                       │
                       ├── ORCID Public API v3.0 search (exact field-scoped query,
                       │      requires ORCID_CLIENT_ID/SECRET — see identifier_types.py)
                       ├── Exactly 1 hit  → status="auto"
                       └── >1 hit          → status="review" (top candidate still
                                             returned, but IdentifierEnricher will NOT
                                             auto-attach it)
```

### Key Design Decisions

- **ROR `chosen:true` only**: ROR explicitly says do NOT use `score` to select matches.
- **Override always wins**: a human-curated `config/overrides.yaml` entry (`IdentifierOverrides`) short-circuits everything else — no network call, not even a cache write.
- **ISNI is checked independently EXCEPT when it would be pure noise**: `resolve()` skips the independent ISNI SRU check only when ROR already returned an unambiguous (`status=="auto"`) match that already carries its own linked ISNI — that check can only ever demote confidence/status (see `_merge_org_matches`), never confirm it. Any other case (ROR found nothing, ROR's match has no ISNI of its own, or ROR's match is itself ambiguous) still checks ISNI independently.
- **Country is a soft hint, not a filter**: the optional `country` param re-ranks ROR `?query=` fuzzy candidates (`fuzzy_matcher.match_organization`'s `country_hint`) — a mismatched candidate is deprioritized by a fixed penalty, never eliminated outright. Folded into the cache key so the same org name in two countries never collides on one cached result.
- **Write every identifier found, where the schema allows it**: `name_identifiers` and `funder_identifiers` are lists — a match carrying both ROR and ISNI writes both entries. `affiliation_identifier` and `publisher_identifier` are singular DataCite fields (0..1 cardinality) — ROR is preferred there when both are available. Every attached identifier also carries its match provenance (`matched_via`/`confidence`/`status`, prefixed for the singular fields) as sibling keys — see `identifier_enricher.py`'s `_identifier_entry`/`_provenance`.
- **ORCID is conservative by design**: a wrong ORCID on a person is worse than a missing one. Ambiguous searches (`status == "review"`) are logged, never auto-attached.
- **Negative caching**: `None` results are cached (both org and person lookups) to avoid repeated API calls for unknown names.
- **Graceful degradation**: All API failures are caught — resolvers never raise, return `None`/empty on failure. Missing ORCID credentials → `ORCIDClient.enabled == False` → silent no-op, not an error.
- **Preserve LLM values**: Enricher only fills EMPTY identifier fields. If the LLM already populated a field, it's preserved.
- **httpx not requests**: Entire codebase uses httpx.
- **DOI resolution scope is deliberately narrow**: `DOIResolverEnricher` only backfills titles, creators (authors), publisher, and an Issued date — the fields Crossref's public Works API reliably returns. Abstracts are skipped (rare, often JATS-XML-tagged when present). Same "preserve LLM values" policy — only ever fills a field that's completely empty.

### Pipeline Integration

```
Pipeline.run() [per resource]:
  0. fetch_page_content(resource.url) → resource.fetched_content   ← only if enable_content_fetch,
                                                                        AND fetched_content is empty,
                                                                        AND resource.url is non-empty
Pipeline._process_resource():
  1. Validate resource
  2. Build agent registry
  3. Orchestrator.run() → agent_results
  4. MetadataMerger.merge() → MetadataDocument
  5. DOIResolverEnricher.enrich(document) → backfilled document ← only if enable_doi_resolution
                                                                     AND resource.identifier_type == "DOI"
  6. IdentifierEnricher.enrich(document, country=detected_country) → enriched document
                                                                   ← only if enable_identifier_enrichment.
                                                                     country computed by pipeline.py itself
                                                                     from resource.url/fetched_content (same
                                                                     CountryExtractor call agents/base.py
                                                                     already makes for the LLM prompt) —
                                                                     the merged document carries no url/
                                                                     country field to read it back from.
  7. validate_pids(document.fields) → warnings                  ← on by default (validate_pids=True)
```

Step 5 runs BEFORE step 6 deliberately — creators/publishers it backfills from Crossref
still get a chance at ROR/ISNI resolution in the identifier-enrichment step right after.

Step 0 runs in `Pipeline._maybe_fetch_content` (pipeline.py), before validation and
before any agent sees the resource — agents read `fetched_content` synchronously while
formatting their prompt (`agents/base.py::BaseAgent._build_resource_dict`), so it must
be populated before the orchestrator's wave executes. It never overwrites
caller-supplied `fetched_content` (this stays a passthrough field by default), and a
failed fetch (`fetch_page_content` returns `None` on any error, by contract) is
silently tolerated — same as not having the feature at all.

Step 7 runs on **every** `process` call, regardless of steps 5/6 — it checks whatever
PIDs are already in the document (LLM-provided or enrichment-added). It never fails
the resource; problems become `PipelineResult.warnings`, same as an incomplete field.

Enable auto content-fetch, DOI resolution, and/or identifier enrichment via config:
```yaml
# config/agents.yaml
enable_content_fetch: true          # default false — off by default: no cost/behavior
                                     # change for existing users unless opted in
enable_doi_resolution: true          # default false — same reasoning
enable_identifier_enrichment: true
identifier_overrides_path: config/overrides.yaml   # optional — default null (feature off)
validate_pids: true       # default — set false to disable entirely
validate_pids_live: true  # default — set false to keep format checks but skip network
```

## CONVENTIONS

- `from __future__ import annotations` first import in every module.
- `model_config = ConfigDict(extra="forbid")` on IdentifierMatch (like all pydantic models except ResourceDescription/MetadataDocument).
- `httpx.Client` for all HTTP calls (never `requests`).
- `diskcache` for caching (SHA-256 key, TTL in seconds). Cache keys are prefixed `org:`/`person:` — an org name and a person's name never collide. Org keys also fold in `country` (normalized: stripped + uppercased before hashing) — same name in two countries never collides either.
- `rapidfuzz` for fuzzy matching (WRatio scorer, threshold 90, gap 5 for review flagging).
- ISNI format: 16-digit unspaced string (e.g. "000000040628717X"). ROR external_ids has spaces — normalized on extraction.
- ORCID format: 16-char hyphenated string (e.g. "0000-0002-1825-0097"), always written as `https://orcid.org/<id>` in `name_identifier`.

## ANTI-PATTERNS

- **NEVER use ROR `score` to select matches** — only `chosen:true` from the affiliation endpoint.
- **NEVER raise from a resolver** — all exceptions caught, return None/empty on failure.
- **NEVER overwrite populated identifier fields** — enricher only fills EMPTY fields.
- **NEVER auto-attach an ambiguous ORCID match** — `status == "review"` must not reach the document unattended.
- **NEVER use `requests`** — this project uses `httpx` exclusively.

## NOTES

- IANANormalizer exists but is NOT wired into the pipeline — a standalone library module.
- CountryExtractor IS wired (unlike the note above about IANANormalizer) — into both agent prompts (`agents/base.py`) and ROR/ISNI matching (`pipeline.py` → `IdentifierEnricher.enrich(country=...)`), computed independently at each site (no shared/cached computation between them).
- The ISNI SRU free endpoint has undocumented rate limiting (~300ms between requests recommended).
- ROR API v1 was sunset December 2025. Only v2 is active (`/v2/organizations`).
- ROR rate limit: 2000/5min per IP (2000/5min with Client-Id header, dropping to 50/5min unauthenticated in Q3 2026).
- ORCID *search* (finding an unknown iD by name, `ORCIDClient.search_person`) requires an OAuth `client_credentials` bearer token from a free self-service registration. Without `ORCID_CLIENT_ID`/`ORCID_CLIENT_SECRET`, ORCID resolution is a silent no-op.
- ORCID *lookup by known iD* is different and needs no token: `pid_validator.resolve_pid` hits `https://orcid.org/{id}` with `Accept: application/orcid+json` (content negotiation) — confirmed live to return 200 with no credentials. This is what makes ORCID PID validation possible even when `ORCID_CLIENT_ID`/`SECRET` are unset.
