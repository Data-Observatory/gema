# Identifier Resolution Improvement Plan (ROR / ORCID / ISNI)

**Created:** 2026-08-25
**Status:** P0 and P1 shipped 2026-08-25 (summary below; full implementation detail in git history — see `feature/identifier-resolution-improvements` and this file's own history via `git log -p -- docs/identifier_resolution_plan.md`). **P2 is the only pending item** — deferred, trigger-conditional, not default work.
**Trigger:** Comparison of `gema`'s identifier-enrichment subsystem against `openalex-guts` (OpenAlex's backend pipeline), reviewed independently by Opus after an initial pass.

## What shipped (P0 + P1, 2026-08-25)

All landed on `feature/identifier-resolution-improvements`, full suite green throughout (897 → 939 passed across the sequence), ruff/mypy clean.

- **Country-aware ROR/ISNI matching.** `ror_client.extract_country`, `fuzzy_matcher.match_organization`'s country hint/penalty, threaded through `identifier_resolver`/`identifier_enricher`/`pipeline.py`, cache key folded to include country. Hint, not gate — never hard-rejects a match, only tie-breaks.
- **Persistent curation override store.** `config/overrides.yaml` + `enrichers/identifier_overrides.py`, checked before cache/network in `IdentifierResolver.resolve()`. `scripts/curate_ror_isni.py` gained a promote-from-review-file mode. Closed the long-open BACKLOG.md curation-step gap.
- **Stopped double-checking ISNI when ROR already links one.** `_merge_org_matches` could only ever *demote* confidence via the independent ISNI-SRU call, never confirm it — corrected the class docstring's false claim and skipped the redundant call. Real behavior change: some prior `"review"` results now come back `"auto"`.
- **Match provenance persisted.** `matched_via`/`confidence`/`status` now travel with every written identifier (creators, affiliations, publishers, funders, overrides) — a curated catalog can show *why* an identifier was attached, not just that it was.
- **Locale-aware name normalization (P1).** Accent folding + a Spanish institutional-abbreviation dict in `fuzzy_matcher.normalize_org_name`, ahead of legal-suffix stripping. Deliberately no acronym dictionary (needs curated ground truth — routed to the overrides store instead) and no Portuguese-specific forms (no corpus data to verify against).

**Explicitly rejected, still holds**: forking/vendoring `openalex-guts` (ops codebase for their own Django/ES/Redshift stack, no stable API to depend on) and cross-corpus author disambiguation (gema has no corpus-wide graph to cluster against — single-resource enrichment by design).

**Flagged but out of scope for this plan** (schema-coverage gaps, not resolution-quality gaps — still unaddressed as of 2026-09-04, not tracked elsewhere): DataCite's `contributors` field (distinct from `creators`) was unmodeled in `schemas/datacite.py`; `funding_references[].funder_identifiers` (ROR now issues funder IDs, Crossref's Funder Registry is a live source) was never pursued as its own enrichment path. Since the CDIF pivot, DataCite generation is exporter-only — worth re-checking whether these still apply to `exporters/datacite.py`'s CDIF→DataCite mapping before picking this back up.

---

## P2 — deferred, trigger-conditional (pending)

### Local ROR-dump ingestion

`openalex-guts` avoids live ROR API calls entirely by batch-loading the full Zenodo ROR dump into an Elasticsearch index on a periodic job (`scripts/update_ror_institutions.py`, ~8h cadence). This is real engineering, but it exists to solve a problem `gema` doesn't have: `openalex-guts` matches hundreds of millions of works against ROR; `gema` calls ROR a handful of times per resource, behind a 30-day diskcache.

**Do not implement by default.** The costs are real for a single-maintainer project: shipping a ~100k-record artifact, building and maintaining a refresh job, and accepting data staleness between refreshes.

**Trigger condition to revisit:** actual observed ROR API rate-limiting in production batch runs, or a concrete requirement for offline/air-gapped operation. "OpenAlex does this" is not sufficient justification on its own.
