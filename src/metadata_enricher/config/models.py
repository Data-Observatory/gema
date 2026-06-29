"""Pydantic models for pipeline configuration.

ProviderConfig, AgentConfig, PipelineConfig — pure data models
with strict validation. No I/O, no parsing.
"""

from __future__ import annotations

from collections import Counter
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderConfig(BaseModel):
    """LLM provider connection settings."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    base_url: str | None = None
    api_key_env: str
    default: bool = False
    seed: int | None = None


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
    use_chain_of_thought: bool = False


class PipelineConfig(BaseModel):
    """Complete pipeline configuration with agents and providers."""

    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(..., min_length=1)
    agents: list[AgentConfig] = Field(..., min_length=1)
    providers: list[ProviderConfig] = Field(..., min_length=1)
    default_provider: str | None = None
    strategies: dict[str, str] = {}
    enable_identifier_enrichment: bool = False

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
