# DataCite 4.6 baseline snapshot (frozen)

Frozen copy of `tests/fixtures/golden/expected/` taken immediately before the CDIF
pivot's golden-fixture re-record (see `docs/codata_mcp_croissant_cdifspecs.md` §6.1),
produced by `config/legacy/agents_datacite46.yaml` (the pre-flip `config/agents.yaml`,
before `schema_name` became `cdif-discovery`). The inputs were the same files as today's
`tests/fixtures/golden/inputs/`.

**Not exercised by `make test` or `make test-regression`** — this is reference
material only, for the A/B diagnostic (`make ab-eval`, spec §9): comparing CDIF-generated →
DataCite-exported output against these DataCite-generated-directly files.

Do not update these files. The original inputs and LLM cache were dropped: the inputs
duplicate `tests/fixtures/golden/inputs/`, and the cache could only replay DataCite-native
generation, which no longer runs since `datacite-4.6` is unregistered. Git history keeps
both if ever needed.
