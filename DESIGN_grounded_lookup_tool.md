# Design: grounded lookup tool for agents

Status: **design only, not implemented**. Written 2026-08-11 per explicit
request to scope this before writing any code — see BACKLOG.md's "Grounded
lookup tool for agents" entry for the motivating problem. For review before
any implementation work starts.

## Problem

`creators_publishers`'s prompt (`config/agents.yaml`) carries a hardcoded
Chile-ministry → affiliation lookup table covering ~15 agencies. For any
institution outside that table, the model falls back to its own parametric
memory to guess the correct official name, ROR-affiliated parent org, or
spelling — ungrounded, and wrong often enough to matter (this is also the
same underlying gap the DOI-resolver enricher and identifier enrichment
partially work around post-hoc, but neither helps the model get the name
*right* in the first place, only resolves an identifier for whatever name
it already produced).

Every agent call today is a single stateless completion: `BaseAgent.run()`
formats one prompt, calls `LLMClient.complete()` once, gets back a fully
populated `DataCiteOutputModel`. There is no mechanism for a model to pause
mid-generation, ask an external system a question, and use the answer —
"grounded" currently means "whatever text happens to be in the prompt."

## Why this is a real architecture change, not a prompt tweak

`InstructorLLMClient.complete()` (`llm/instructor_client.py`) already uses
OpenAI-style tool-calling under the hood — Instructor forces a single
"extract these fields" tool call to get structured output. That's a
different thing from what's being asked for here: a tool the model can
**choose** to call zero or more times mid-reasoning (e.g. "look up the
official name for 'Minsal'"), see the result, and only then produce its
final structured output.

The standard pattern for that (OpenAI's own recommended flow) is a loop:

```
messages = [system, user]
loop:
    response = raw_client.chat.completions.create(messages, tools=[lookup_tool])
    if response has tool_calls:
        for each tool_call: execute it, append {"role": "tool", ...} result
        continue loop
    else:
        break  # model is done calling tools
final = instructor_client.chat.completions.create(messages, response_model=DataCiteOutputModel)
```

This is a materially different code path from today's single `complete()`
call, and it only makes sense for the one agent that actually needs it
(`creators_publishers`) — every other agent gaining tool-calling machinery
for no reason would add latency/cost/failure-surface with no benefit.

## Recommended backing: reuse `RORClient`, not a new web-search integration

Two options were on the table (per the original backlog wording: "web
search or a static gazetteer function-call"):

1. **Live web search.** Most general, but: needs a new external dependency
   (a search API — Brave/Serper/Google — none currently used in this repo),
   a new API key/cost line, unpredictable result quality, and a much larger
   surface to get wrong (parsing arbitrary search results).
2. **A static gazetteer, re-exposed as a callable tool.** This is just
   today's ~15-entry hardcoded table, callable instead of inlined — doesn't
   fix the actual coverage gap unless someone also does the work of growing
   the table, which is a data-curation task, not a code task.
3. **Reuse `RORClient`** (`enrichers/ror_client.py`, already built, already
   tested, already fixed tonight — see the `limit`-param bug fix). ROR
   covers a huge number of organizations worldwide, including many
   government ministries (confirmed empirically tonight: ROR has multiple
   countries' "Ministerio de Salud" entries, for example). Exposing
   `lookup_organization(name) -> {ror_id, canonical_name, parent_org}` as a
   tool the `creators_publishers` agent can call mid-generation is a live,
   free, no-new-dependency, already-tested grounding source — and it's the
   *same* registry `IdentifierEnricher` already resolves against post-hoc,
   so a name the tool confirms during generation is also a name that will
   resolve cleanly afterward.

**Recommendation: option 3.** It's the smallest real fix that actually
grounds the model instead of moving the same guess earlier or later in the
pipeline. Web search stays a reasonable follow-up if ROR coverage turns out
to be insufficient in practice, but that should be measured, not assumed.

## Scope of the actual change

1. `llm/base.py`: extend the `LLMClient` Protocol (or add a new
   duck-typed optional method, same pattern as `complete_with_usage`) with
   something like:
   ```python
   def complete_with_tools(
       self, prompt: str, response_model: type[BaseModel], tools: list[ToolSpec],
       tool_executor: Callable[[str, dict], str], system_prompt: str | None = None,
   ) -> BaseModel: ...
   ```
   implemented only in `InstructorLLMClient`, following the tool-call loop
   above. Mocks/fakes that don't implement it simply don't get tool support
   (same graceful-degradation pattern `complete_with_usage`'s `getattr`
   check already uses in `BaseAgent.run()`).
2. `agents/base.py`: `BaseAgent` gains an optional `tools` param. Only
   `creators_publishers`'s `AgentConfig` would set it (new YAML field,
   e.g. `tools: [ror_lookup]`); every other agent's behavior is byte-for-byte
   unchanged.
3. A small `ror_lookup_tool.py` (or a function inside `crossref_client.py`'s
   sibling module) exposing `RORClient.search_affiliation`/`search_query` as
   an OpenAI tool-call schema + executor. Same graceful-degradation
   philosophy as every other enricher here: a tool-call failure must
   *never* abort generation — return an empty/error string as the tool
   result and let the model proceed with whatever it already had.
4. `config/agents.yaml`: new prompt language for `creators_publishers`
   telling it when to call the tool (an institution name it's unsure about
   or that isn't in the ~15-entry table) and how to use the result (prefer
   the tool's canonical name over a guess; if the tool finds nothing, fall
   back to today's behavior — never block on it).

## Cost / latency impact

Each tool-call round-trip is a full extra LLM request (the loop above).
Worst case (model calls the tool once before finishing): roughly 2x latency
and token cost for `creators_publishers` specifically, on inputs where it
actually needs to look something up. Needs a cap (e.g. max 2 tool-call
rounds before forcing a final answer) to bound worst-case cost — an LLM that
gets stuck calling the tool repeatedly must not be allowed to loop
indefinitely.

## Testing plan

- Unit: mock the tool executor, verify the loop terminates, verify a
  tool-call failure doesn't propagate as an agent failure (same pattern as
  every other enricher's try/except-and-degrade tests in this repo).
- Golden fixtures: this changes `creators_publishers`'s prompt and output
  shape not at all (same `DataCiteOutputModel` fields) but changes its
  *process* — expect no golden-fixture diff unless the tool actually fires
  on one of the 6 golden inputs, in which case re-record as usual.
- Live smoke test (mirrors this session's `context_hints` verification):
  run `creators_publishers` alone against a resource naming an institution
  known to be outside the ~15-entry table but present in ROR, with/without
  the tool enabled, and confirm the tool-enabled run produces the correct
  canonical name while the disabled run still guesses.

## Rollout

Pilot on `creators_publishers` only, `--pilot-only` do_catalog re-run
(deepseek-only, same cheap-comparison pattern used tonight) to check for a
real quality delta before deciding whether it's worth the added
latency/cost for production use. Do **not** roll out to other agents
without a similar measured pilot per agent.

## Explicitly out of scope for this doc

- Growing the static ~15-entry table (a data-curation task, orthogonal to
  this — could still be done independently, cheaply, regardless of whether
  this tool-calling work ever ships).
- Web search integration (deferred pending evidence that ROR coverage is
  insufficient).
- Any other agent gaining tool access.
