# Backlog

Deferred, non-urgent improvements surfaced during development — not tracked
elsewhere (no issue tracker in use for this repo). Each item should carry
enough context to pick up cold; prune entries once actually done.

## Agents / prompts

- **Grounded lookup tool for agents (web search or a static gazetteer
  function-call), instead of relying on the model's parametric knowledge.**
  `creators_publishers`'s hardcoded Chile-ministry→affiliation lookup table
  only covers ~15 agencies; anything else, the model guesses from memory,
  ungrounded. Real fix needs actual tool-calling (Instructor/OpenAI function
  calling), not a prompt tweak. Same underlying gap as the DOI-resolver idea
  below — nothing in this pipeline can currently "look things up," every
  agent call is a stateless completion over whatever text is in the prompt.
- **Shared `system_prompt` to stop the 5 agent prompts drifting out of
  sync.** `AgentConfig.system_prompt` exists but is unused (`None` for every
  agent in `config/agents.yaml`). Boilerplate ("NUNCA usar null",
  "Devolver SOLO JSON valido", chain-of-thought framing) is duplicated
  5x with no mechanism keeping the copies consistent.
- **`depends_on: []` for all 5 agents vs. CLAUDE.md's documented sequential
  pipeline** (`core_metadata -> creators_publishers -> ...`). Since no
  agent's prompt references another agent's output, parallel (current
  config) is probably correct and the doc is just stale — confirm and fix
  the doc, or find a real dependency that got dropped.
- **DOI-resolver enricher**: for DOI-identified resources, fetch real
  Crossref/DataCite metadata to backfill weak/missing fields, instead of
  relying purely on LLM extraction from title/description text. Flagged
  out of scope during the do_catalog eval work.

## Identifier enrichment

- **Curated, human-reviewed ROR/ISNI ground truth** to replace the messy
  source data (do_catalog's raw VIAF/Wikidata/malformed-ISNI identifiers
  aren't reliable as strict ROR-only ground truth — the eval's scoring
  adapter works around this with scheme-aware matching, but the underlying
  source data quality issue is untouched).

## Pipeline / infra

- **`max_workers` bump when production model moves off zai-coding-plan.**
  Currently pinned to 1 (`4101ac9`) because that provider's account rate
  limit is tight (429s even at `max_workers=2`). Confirmed empirically this
  session: `opencode:deepseek-v4-flash` handles `max_workers=5` with zero
  429s, ~3x wall-clock speedup per resource (18.7s vs ~57s summed). Safe to
  raise only if/when the default provider actually changes — don't touch it
  while still on glm-5.2.
- **mimo-v2.5's pathological slowness on content-dense inputs.** Same DOI
  resource (`136`, GFZ dataset, 6000-char fetched_content) caused a 1201s
  stall for glm-5-turbo and a 3244s (54min) stall for mimo-v2.5 in the same
  eval run. Investigate before treating mimo-v2.5 as a real production
  candidate — a single bad input shouldn't be able to blow up wall-clock by
  that much.
- **Real production content-fetch, not just the eval harness's.** See
  `feature/auto-content-fetch` branch (commit `af7c265`) — built, tested,
  unmerged. Once merged, decide whether to default it on for do_catalog-like
  callers and whether input size (max_len) needs tuning given the mimo-v2.5
  finding above (large fetched_content correlates with the worst stalls).

## Eval harness

- **Full-100 do_catalog scale-up** — pilot (18 main + 20 ORCID) x2 (v1/v2)
  complete; full 100 pre-approved in scope but not yet run. Cost/time should
  be re-estimated now that `--fetch` is in the mix (real per-item network
  latency) and given the mimo-v2.5 timing risk above.
