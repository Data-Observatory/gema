# DataCite 4.6 baseline snapshot (frozen)

Frozen copy of `tests/fixtures/golden/{inputs,expected,cache}` taken immediately
before the CDIF pivot's golden-fixture re-record (`docs/cdif_pivot_implementation_plan.md`
Step 2f), paired with `config/legacy/agents_datacite46.yaml` (the pre-flip
`config/agents.yaml`, before `schema_name` became `cdif-discovery`).

**Not exercised by `make test` or `make test-regression`** — this is reference
material only, for the A/B diagnostic (spec §9): comparing CDIF-generated →
DataCite-exported output against DataCite-generated-directly output, using
`schemas.datacite.DataCiteSchema46` instantiated directly (it is no longer
registered in `schemas/__init__.py`'s registry, but the class still works
standalone).

Do not update these files. If DataCite generation is ever needed again for
comparison, run the pipeline with `config/legacy/agents_datacite46.yaml`
against `inputs/` here with a fresh cache.
