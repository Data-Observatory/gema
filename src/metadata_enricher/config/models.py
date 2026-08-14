"""Pydantic models for pipeline configuration.

ProviderConfig, AgentConfig, PipelineConfig — pure data models
with strict validation. No I/O, no parsing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    enable_content_fetch: bool = False
    enable_doi_resolution: bool = False
    validate_pids: bool = True
    validate_pids_live: bool = True

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

        if self.default_provider is not None and self.default_provider not in provider_names:
            msg = (
                f"default_provider '{self.default_provider}' not found in providers. "
                f"Available: {sorted(provider_names)}"
            )
            raise ValueError(msg)

        for agent in self.agents:
            if agent.provider not in provider_names:
                msg = (
                    f"agent '{agent.id}' references provider '{agent.provider}' "
                    f"which is not in providers. Available: {sorted(provider_names)}"
                )
                raise ValueError(msg)

            for dep in agent.depends_on:
                if dep not in agent_ids:
                    msg = (
                        f"agent '{agent.id}' depends_on '{dep}' "
                        f"which is not a known agent ID. Available: {sorted(agent_ids)}"
                    )
                    raise ValueError(msg)

        if len(agent_ids) != len(self.agents):
            counter = Counter(a.id for a in self.agents)
            duplicates = {id_ for id_, count in counter.items() if count > 1}
            msg = f"duplicate agent IDs found: {sorted(duplicates)}"
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
