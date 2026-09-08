"""Pydantic models for pipeline configuration.

ProviderConfig, AgentConfig, PipelineConfig — pure data models
with strict validation. No I/O, no parsing.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

# Which wire format a provider/model speaks. "chat_completions" is the
# universal OpenAI-compatible baseline every provider in this repo supports
# today; "responses" opts a specific model into OpenAI's newer Responses API
# (POST /responses) instead -- needed for models that don't work at all over
# Chat Completions (e.g. opencode's muse-spark family, confirmed 2026-09-06:
# real HTTP 500 from Chat Completions, HTTP 200 from Responses, same key).
ApiStyle = Literal["chat_completions", "responses"]

# Real values taken verbatim from openai.types.shared.reasoning_effort.
# "provider_default" is a gema-only sentinel meaning "omit the reasoning
# block entirely and let the endpoint pick" -- an explicit, greppable opt-out
# rather than an accidental omission. Only meaningful when api_style is
# "responses"; ignored for chat_completions models.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "provider_default"]

DEFAULT_API_STYLE: ApiStyle = "chat_completions"

# Probed 2026-09-06 against opencode:muse-spark-1.3-contributor, single
# prompt ("What is the capital of France? Answer in one word.",
# max_output_tokens=600): low=202 output tokens, medium=189, high=254, all
# three answered correctly. That is one data point per tier -- far too small
# a sample to responsibly pick the cheapest option ("low") as the default
# every agent run silently inherits. "medium" is the deliberate, more
# conservative starting default pending real-world data from actual agent
# runs -- not a reversal of the probe's finding (medium/low still look
# roughly comparable), just a more cautious read of weak data. It remains
# strictly cheaper than the endpoint's own unrequested default (observed to
# be "high" when the reasoning block is omitted entirely, which burned 534
# reasoning tokens on "say hello world" in an earlier probe).
DEFAULT_RESPONSES_REASONING_EFFORT: ReasoningEffort = "medium"


class ModelOverride(BaseModel):
    """Per-model setting override, scoped to one provider.

    Keyed by model name only within a single ProviderConfig's own
    model_overrides list — the same model name can exist under different
    providers with different characteristics (rate limits, concurrency
    tolerance), so an override must never be looked up by model name alone.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., min_length=1)
    max_workers: int | None = Field(default=None, ge=1)
    # None on either field means "inherit from the owning ProviderConfig",
    # exactly like max_workers above -- see ProviderConfig.effective_api_style
    # / effective_reasoning_effort for the cascade.
    api_style: ApiStyle | None = None
    reasoning_effort: ReasoningEffort | None = None


class ProviderConfig(BaseModel):
    """LLM provider connection settings."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    base_url: str | None = None
    api_key_env: str
    default: bool = False
    seed: int | None = None
    max_workers: int | None = Field(default=None, ge=1)
    model_overrides: list[ModelOverride] = Field(default_factory=list)
    # Header name to stamp with a fresh random ID once per LLM "conversation"
    # (one complete()/complete_with_usage()/complete_with_tools()/complete_raw()
    # call -- reused across that call's own retries/tool-loop rounds, never
    # across separate calls). OpenCode requires this ("x-opencode-session")
    # to tell concurrent conversations apart for its own routing/optimization
    # -- see llm/instructor_client.py's _build_extra_headers. Never enters the
    # disk cache key (cache.py): it's random by design, so putting it there
    # would break every cache hit.
    session_header: str | None = None
    api_style: ApiStyle = DEFAULT_API_STYLE
    reasoning_effort: ReasoningEffort | None = None

    def effective_api_style(self, model: str) -> ApiStyle:
        """Resolve wire format with 2-level cascading precedence: this
        provider's own api_style (least specific, defaults to
        "chat_completions") -> its per-model override for *model* (most
        specific). model is looked up ONLY within this provider's own
        model_overrides -- same rule as effective_max_workers.
        """
        for override in self.model_overrides:
            if override.model == model and override.api_style is not None:
                return override.api_style
        return self.api_style

    def effective_reasoning_effort(self, model: str) -> ReasoningEffort:
        """Resolve reasoning effort with 3-level cascading precedence: the
        hardcoded conservative default (least specific) -> this provider's
        own reasoning_effort -> its per-model override for *model* (most
        specific). Only meaningful when effective_api_style(model) ==
        "responses"; callers on the chat_completions path ignore this.
        """
        if self.reasoning_effort is not None:
            effective = self.reasoning_effort
        else:
            effective = DEFAULT_RESPONSES_REASONING_EFFORT

        for override in self.model_overrides:
            if override.model == model and override.reasoning_effort is not None:
                effective = override.reasoning_effort

        return effective


def find_model_override_elsewhere(
    providers: list[ProviderConfig], model: str, assigned_provider: str
) -> str | None:
    """Return another provider's name that carries an api_style or
    reasoning_effort override for *model* which *assigned_provider*
    doesn't actually resolve to -- a likely misconfiguration signal, not
    an error: model_overrides is deliberately scoped per-provider (see
    ModelOverride's docstring), so assigning a model to a provider that
    lacks the override it needs (e.g. api_style: responses for a model
    that 400s on chat_completions) silently falls back to that provider's
    own default instead of failing loudly. Callers decide what to do with
    the answer (visor surfaces a warning; nothing here blocks the
    assignment, since a provider genuinely not needing any override for
    this model is a normal, valid case too).

    Compares actual *resolved* values (via effective_api_style/
    effective_reasoning_effort), not mere presence of a model_overrides
    entry for *model* -- found on review: a provider carrying an entry for
    *model* that sets, say, only max_workers (leaving api_style/
    reasoning_effort to cascade down to that provider's own plain default)
    must still be flagged if another provider's api_style/reasoning_effort
    override for the same model would actually resolve differently; the
    mere existence of *an* entry doesn't mean the field that matters is
    covered.

    Returns None when *assigned_provider* already resolves to the same
    values another provider's override would give, or no provider's
    override would actually change anything (nothing to warn about).
    """
    assigned = next((p for p in providers if p.name == assigned_provider), None)
    for provider in providers:
        if provider.name == assigned_provider:
            continue
        for override in provider.model_overrides:
            if override.model != model:
                continue
            if override.api_style is not None and (
                assigned is None or assigned.effective_api_style(model) != override.api_style
            ):
                return provider.name
            if override.reasoning_effort is not None and (
                assigned is None
                or assigned.effective_reasoning_effort(model) != override.reasoning_effort
            ):
                return provider.name
    return None


class AgentConfig(BaseModel):
    """Single agent definition within a pipeline."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    name: str
    description: str = ""
    fields: list[str] = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    system_prompt: str | None = None
    provider: str
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    # Overrides the resolved provider/model reasoning effort for this agent
    # only -- e.g. give one hard agent more thinking budget without paying
    # for it on every other agent. Meaningless (and warned about at pipeline
    # construction, see PipelineConfig._validate_references) for an agent
    # whose resolved provider/model is on the chat_completions api_style --
    # deliberately a warning, not an error, so a single agents.yaml keeps
    # working across scripts/compare_models.py's in-place model swaps.
    reasoning_effort: ReasoningEffort | None = None
    depends_on: list[str] = []
    # Top-level field names this agent wants surfaced from its dependencies'
    # already-merged output (e.g. ["resource", "publishers"]) -- only
    # meaningful alongside depends_on, since only prior-wave results are
    # ever available. See BaseAgent.run()'s upstream_fields param and
    # orchestrator.py's wave-result threading.
    context_fields: list[str] = []
    use_chain_of_thought: bool = False
    # Passed straight through to the OpenAI-compatible request body. Needed for
    # provider/model-specific knobs standard fields don't cover — e.g. disabling
    # DeepSeek V4's "thinking mode" (extra_body={"thinking": {"type": "disabled"}}),
    # required because Instructor's forced tool_choice isn't supported alongside it.
    extra_body: dict[str, Any] | None = None
    # Names of tools (see llm/tools.py's TOOL_REGISTRY) this agent may call
    # mid-reasoning via BaseAgent's tool-call loop, before its final forced
    # structured-output call. Empty by default -- most agents never see a
    # tools= request at all. Validated against TOOL_REGISTRY at pipeline
    # construction (see PipelineConfig._validate_references).
    tools: list[str] = []


class PipelineConfig(BaseModel):
    """Complete pipeline configuration with agents and providers."""

    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(..., min_length=1)
    agents: list[AgentConfig] = Field(..., min_length=1)
    providers: list[ProviderConfig] = Field(..., min_length=1)
    default_provider: str | None = None
    strategies: dict[str, str] = {}
    max_workers: int = Field(default=4, ge=1)
    enable_identifier_enrichment: bool = False
    # Path to a human-curated overrides.yaml (see enrichers/identifier_overrides.py),
    # checked before any ROR/ISNI network call. Resolved relative to the current
    # working directory, same as --config/--output. None (default) disables it --
    # a missing/unset path is not an error, matching this feature's fail-soft design.
    identifier_overrides_path: str | None = None
    enable_content_fetch: bool = False
    enable_doi_resolution: bool = False
    validate_pids: bool = True
    validate_pids_live: bool = True
    # Non-blocking SHACL conformance check (schemas/cdif/discovery/shacl.ttl)
    # run as a post-merge pipeline step, warnings only -- see
    # CDIFDiscoveryProfile.check_shacl_conformance's own docstring for the
    # mechanics. Defaults to False, unlike validate_pids above: PID
    # validation is a mature, already-tuned check every user benefits from;
    # this one is new and, as of this writing, every real recorded golden
    # fixture fails it (mostly for reasons outside gema's direct control --
    # see docs/cdif_pivot_implementation_plan.md's "Step 6" notes) -- so
    # defaulting it on today would flood every existing user with warnings
    # they have no way to act on yet. Opt in once you want visibility into
    # CDIF conformance gaps for your own generated documents. Only takes
    # effect when the registered schema actually implements
    # check_shacl_conformance (CDIFDiscoveryProfile does; a hypothetical
    # future schema that doesn't is silently skipped, not an error).
    validate_shacl_conformance: bool = False

    def effective_max_workers(
        self, provider_name: str | None = None, model_name: str | None = None
    ) -> int:
        """Resolve concurrency with 3-level cascading precedence: this
        config's global max_workers (least specific) -> the named
        provider's own max_workers override -> that provider's per-model
        override for *model_name* (most specific).

        model_name is looked up ONLY within provider_name's own
        model_overrides — the same model name can mean something different
        under a different provider, so it is never matched globally.

        This is the single place that resolves the effective value; no
        caller should hardcode a provider or model name to special-case its
        concurrency.
        """
        effective = self.max_workers

        if provider_name is not None:
            for provider in self.providers:
                if provider.name != provider_name:
                    continue
                if provider.max_workers is not None:
                    effective = provider.max_workers
                if model_name is not None:
                    for override in provider.model_overrides:
                        if override.model == model_name and override.max_workers is not None:
                            effective = override.max_workers
                break

        return effective

    @model_validator(mode="after")
    def _validate_references(self) -> Self:
        provider_names = {p.name for p in self.providers}
        agent_ids = {a.id for a in self.agents}
        agents_by_id = {a.id: a for a in self.agents}

        if self.default_provider is not None and self.default_provider not in provider_names:
            msg = (
                f"default_provider '{self.default_provider}' not found in providers. "
                f"Available: {sorted(provider_names)}"
            )
            raise ValueError(msg)

        providers_by_name = {p.name: p for p in self.providers}

        for provider in self.providers:
            override_models = [o.model for o in provider.model_overrides]
            dupes = {m for m, count in Counter(override_models).items() if count > 1}
            if dupes:
                msg = (
                    f"provider '{provider.name}' has duplicate model_overrides "
                    f"entries for model(s): {sorted(dupes)}"
                )
                raise ValueError(msg)

        for agent in self.agents:
            if agent.provider not in provider_names:
                msg = (
                    f"agent '{agent.id}' references provider '{agent.provider}' "
                    f"which is not in providers. Available: {sorted(provider_names)}"
                )
                raise ValueError(msg)

            if agent.reasoning_effort is not None:
                provider = providers_by_name[agent.provider]
                resolved_model = agent.model or ""
                if provider.effective_api_style(resolved_model) == "chat_completions":
                    logger.warning(
                        "agent '%s' sets reasoning_effort but resolves to a "
                        "chat_completions model (provider '%s', model '%s') -- "
                        "ignored on that path",
                        agent.id,
                        agent.provider,
                        resolved_model,
                    )

            for dep in agent.depends_on:
                if dep not in agent_ids:
                    msg = (
                        f"agent '{agent.id}' depends_on '{dep}' "
                        f"which is not a known agent ID. Available: {sorted(agent_ids)}"
                    )
                    raise ValueError(msg)

            if agent.context_fields:
                # Only fields produced by a (transitive) depends_on ancestor are
                # ever guaranteed to land in Orchestrator.run()'s accumulated
                # upstream_fields dict before this agent's own wave runs -- a
                # typo'd or unrelated field name here would silently inject
                # nothing at runtime (BaseAgent.run() drops anything not found
                # in upstream_fields) instead of failing loudly here.
                reachable_fields: set[str] = set()
                seen_ancestors: set[str] = set()
                stack = list(agent.depends_on)
                while stack:
                    dep_id = stack.pop()
                    if dep_id in seen_ancestors:
                        continue
                    seen_ancestors.add(dep_id)
                    dep_agent = agents_by_id.get(dep_id)
                    if dep_agent is None:
                        # Unknown ID -- reported by the depends_on check above,
                        # either for this agent or for whichever agent lists it.
                        continue
                    reachable_fields.update(dep_agent.fields)
                    stack.extend(dep_agent.depends_on)

                unknown_fields = [f for f in agent.context_fields if f not in reachable_fields]
                if unknown_fields:
                    msg = (
                        f"agent '{agent.id}' context_fields {unknown_fields} not produced by "
                        f"any depends_on ancestor ({sorted(agent.depends_on)}). "
                        f"Available: {sorted(reachable_fields)}"
                    )
                    raise ValueError(msg)

            if agent.tools:
                # Local import -- config/models.py must stay import-light (no
                # network/heavy deps at module load), and llm/tools.py's
                # TOOL_REGISTRY is only needed for this one validation check.
                from metadata_enricher.llm.tools import TOOL_REGISTRY

                unknown_tools = [t for t in agent.tools if t not in TOOL_REGISTRY]
                if unknown_tools:
                    msg = (
                        f"agent '{agent.id}' tools {unknown_tools} not found in "
                        f"TOOL_REGISTRY. Available: {sorted(TOOL_REGISTRY)}"
                    )
                    raise ValueError(msg)

        if len(agent_ids) != len(self.agents):
            counter = Counter(a.id for a in self.agents)
            duplicates = {id_ for id_, count in counter.items() if count > 1}
            msg = f"duplicate agent IDs found: {sorted(duplicates)}"
            raise ValueError(msg)

        if len(provider_names) != len(self.providers):
            # Unlike two providers sharing one api_key_env (legitimate --
            # e.g. the same account key against two base_urls), two
            # providers sharing a *name* is never valid: agents and
            # default_provider both reference a provider by name alone,
            # so a duplicate makes that reference ambiguous and silently
            # degrades to "whichever one a name-keyed lookup happens to
            # find" wherever providers are looked up by name.
            provider_counter = Counter(p.name for p in self.providers)
            provider_duplicates = {name for name, count in provider_counter.items() if count > 1}
            msg = f"duplicate provider names found: {sorted(provider_duplicates)}"
            raise ValueError(msg)

        return self


class DataverseExportConfig(BaseModel):
    """Config for the DataCite -> Dataverse export's one LLM-assisted step
    (classifying into Dataverse's required, fixed Subject vocabulary —
    see exporters/dataverse.py for why that's the only field genuinely
    ambiguous enough to need one).

    `agent` reuses AgentConfig as-is — the exact same provider/model/
    temperature/prompt shape every pipeline agent uses, configurable the
    same way — even though this never runs through the orchestrator (it's
    a single classification call, not a multi-agent extraction, so there's
    no PipelineConfig/schema/providers list of its own here; the provider
    name is cross-validated against whichever providers list the caller
    already loaded from config/providers.yaml).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    agent: AgentConfig

    def validate_provider_exists(self, provider_names: set[str]) -> None:
        if self.agent.provider not in provider_names:
            msg = (
                f"dataverse export agent references provider '{self.agent.provider}' "
                f"which is not in providers. Available: {sorted(provider_names)}"
            )
            raise ValueError(msg)
