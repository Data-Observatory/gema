# enrichers/

Post-merge enrichment modules. Deterministic transforms applied to `MetadataDocument` after the LLM agent pipeline.

## STRUCTURE

```
enrichers/
├── __init__.py                  # Exports IdentifierEnricher, IdentifierResolver, IdentifierMatch
├── iana_normalizer.py           # MIME type normalization against IANA registry (standalone, not wired)
├── country_extractor.py         # ISO country code extraction from HTML/URL (standalone, not wired)
├── identifier_types.py          # IdentifierMatch pydantic model (resolved org identifier)
├── ror_client.py                # ROR API v2 client (affiliation + query endpoints)
├── isni_client.py               # ISNI SRU client (XML parsing via httpx + ElementTree)
├── fuzzy_matcher.py             # rapidfuzz WRatio org name matching + normalization
├── identifier_resolver.py       # Fallback chain: ROR affiliation → ROR query+fuzzy → ISNI
└── identifier_enricher.py       # Post-merge document enrichment (creators, publishers, funding)
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Enable identifier enrichment | `PipelineConfig.enable_identifier_enrichment = True` (config/models.py) |
| Change resolution order | `IdentifierResolver._try_resolve()` (identifier_resolver.py) |
| Change fuzzy threshold | `IdentifierResolver.__init__(fuzzy_threshold=90.0)` |
| Change cache TTL | `IdentifierResolver.__init__(cache_ttl=timedelta(days=30))` |
| Change cache dir | `IdentifierResolver.__init__(cache_dir=Path(...))` |
| Add new identifier field | `IdentifierEnricher._enrich_*()` methods |
| Skip certain creators | Check `creator_name_type` in `_enrich_creators()` |

## IDENTIFIER RESOLUTION ARCHITECTURE

```
Organization name → IdentifierResolver.resolve(name)
                       │
                       ├── 1. Check diskcache (~/.cache/metagen/identifiers/, 30-day TTL)
                       │      Hit? → return cached IdentifierMatch or None (negative cache)
                       │
                       ├── 2. ROR ?affiliation= endpoint
                       │      Returns chosen:true for best match → build IdentifierMatch
                       │
                       ├── 3. ROR ?query= + rapidfuzz WRatio (threshold 90)
                       │      Fuzzy match against candidate names → build IdentifierMatch
                       │
                       ├── 4. ISNI SRU pica.nw + rapidfuzz WRatio
                       │      Fuzzy match → build IdentifierMatch (ISNI only, no ROR)
                       │
                       └── Cache result (positive or negative) → return
```

### Key Design Decisions

- **ROR `chosen:true` only**: ROR explicitly says do NOT use `score` to select matches.
- **Negative caching**: None results are cached to avoid repeated API calls for unknown orgs.
- **Graceful degradation**: All API failures are caught — resolver never raises, returns None.
- **Personal creators skipped**: `creator_name_type == "Personal"` → no ROR lookup (individuals).
- **Preserve LLM values**: Enricher only fills EMPTY identifier fields. If the LLM already populated a field, it's preserved.
- **httpx not requests**: Entire codebase uses httpx. ROR and ISNI clients both use httpx.Client.

### Pipeline Integration

```
Pipeline._process_resource():
  1. Validate resource
  2. Build agent registry
  3. Orchestrator.run() → agent_results
  4. MetadataMerger.merge() → MetadataDocument
  5. [NEW] IdentifierEnricher.enrich(document) → enriched document  ← only if enabled
```

Enable via config:
```yaml
# config/agents.yaml
enable_identifier_enrichment: true
```

Or programmatically:
```python
config = PipelineConfig(..., enable_identifier_enrichment=True)
pipeline = Pipeline(config)
```

## CONVENTIONS

- `from __future__ import annotations` first import in every module.
- `model_config = ConfigDict(extra="forbid")` on IdentifierMatch (like all pydantic models except ResourceDescription/MetadataDocument).
- `httpx.Client` for all HTTP calls (never `requests`).
- `diskcache` for caching (SHA-256 key, TTL in seconds).
- `rapidfuzz` for fuzzy matching (WRatio scorer, threshold 90, gap 5 for review flagging).
- ISNI format: 16-digit unspaced string (e.g. "000000040628717X"). ROR external_ids has spaces — normalized on extraction.

## ANTI-PATTERNS

- **NEVER use ROR `score` to select matches** — only `chosen:true` from the affiliation endpoint.
- **NEVER raise from the resolver** — all exceptions caught, return None on failure.
- **NEVER overwrite populated identifier fields** — enricher only fills EMPTY fields.
- **NEVER resolve Personal creators** — individuals don't have ROR IDs.
- **NEVER use `requests`** — this project uses `httpx` exclusively.

## NOTES

- IANANormalizer and CountryExtractor exist but are NOT wired into the pipeline. They are standalone library modules.
- The ISNI SRU free endpoint has undocumented rate limiting (~300ms between requests recommended).
- ROR API v1 was sunset December 2025. Only v2 is active (`/v2/organizations`).
- ROR rate limit: 2000/5min per IP (2000/5min with Client-Id header, dropping to 50/5min unauthenticated in Q3 2026).
