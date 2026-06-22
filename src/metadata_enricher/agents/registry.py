"""Registry that builds BaseAgent instances from pipeline config."""

from __future__ import annotations

import logging
from typing import Callable

from metadata_enricher.agents.base import BaseAgent
from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import create_llm_client
from metadata_enricher.schemas import get_registry as get_schema_registry
from metadata_enricher.schemas.base import Schema, SchemaRegistry

logger = logging.getLogger(__name__)

LLMClientFactory = Callable[[ProviderConfig, str, float, int | None], LLMClient]


class AgentRegistry:
    """Builds and manages BaseAgent instances from pipeline configuration.

    Each agent in the config gets a BaseAgent instance with its provider's
    LLMClient wired in. Agents sharing the same provider share the same
    LLMClient instance (cached by provider name in the factory).
    """

    def __init__(
        self,
        config: PipelineConfig,
        schema: Schema | None = None,
        schema_registry: SchemaRegistry | None = None,
        llm_factory: LLMClientFactory | None = None,
    ) -> None:
        self._config = config
        self._llm_factory = llm_factory or create_llm_client

        if schema is not None:
            self._schema = schema
        else:
            sr = schema_registry or get_schema_registry()
            self._schema = sr.get(config.schema_name)

        self._providers: dict[str, ProviderConfig] = {p.name: p for p in config.providers}

        self._agents: dict[str, BaseAgent] = {}
        self._build_agents()

    def _build_agents(self) -> None:
        for agent_config in self._config.agents:
            provider = self._providers.get(agent_config.provider)
            if provider is None:
                raise ValueError(
                    f"Agent '{agent_config.id}' references unknown provider '{agent_config.provider}'. "
                    f"Available: {list(self._providers.keys())}"
                )

            llm_client = self._llm_factory(
                provider,
                model=agent_config.model,
                temperature=agent_config.temperature,
                max_tokens=agent_config.max_tokens,
            )

            agent = BaseAgent(
                name=agent_config.name,
                fields=agent_config.fields,
                prompt=agent_config.prompt,
                llm_client=llm_client,
                schema=self._schema,
                system_prompt=agent_config.system_prompt,
            )
            self._agents[agent_config.id] = agent
            logger.debug(
                "Built agent '%s' (provider=%s, model=%s)",
                agent_config.id,
                agent_config.provider,
                agent_config.model,
            )

    def get_agent(self, name: str) -> BaseAgent:
        """Get an agent by its id. Raises KeyError if not found."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not found. Available: {list(self._agents.keys())}")
        return self._agents[name]

    def get_all_agents(self) -> list[BaseAgent]:
        """Get all agents in registration order."""
        return list(self._agents.values())

    def get_agent_configs(self) -> list[AgentConfig]:
        """Get all agent configs (for dependency resolution)."""
        return list(self._config.agents)

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """Return agent_id -> list of depends_on ids."""
        return {ac.id: list(ac.depends_on) for ac in self._config.agents}

    @property
    def schema(self) -> Schema:
        return self._schema
