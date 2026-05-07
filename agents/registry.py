"""Agent registry for loading and managing agents."""

import json
import logging
from pathlib import Path

from agents.base import BaseAgent
from schemas.agent_config_schema import AgentsConfig, ProvidersConfig

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry for loading and managing agents from config."""

    def __init__(
        self,
        config_path: str,
        api_key: str = "",
        llm_timeout: int | None = None,
        cache_enabled: bool = True,
    ):
        self.config_path = Path(config_path)
        self.api_key = api_key
        self.llm_timeout = llm_timeout
        self.cache_enabled = cache_enabled
        self._config: AgentsConfig | None = None
        self._providers_config = ProvidersConfig.load()
        self._load_config()

    def _load_config(self) -> None:
        """Load agent configuration from JSON file."""
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._config = AgentsConfig(**data)

        errors = self._config.validate_dependencies()
        if errors:
            raise ValueError(f"Invalid agent configuration: {errors}")

    def load_agents(self) -> dict[str, BaseAgent]:
        """Create agent instances from config."""
        if self._config is None:
            raise ValueError("Config not loaded")
        self._agents = {}
        for agent_config in self._config.agents:
            if self.llm_timeout is not None:
                agent_config = agent_config.model_copy(
                    update={
                        "llm_config": agent_config.llm_config.model_copy(
                            update={"timeout": self.llm_timeout}
                        )
                    }
                )
            self._agents[agent_config.id] = BaseAgent(
                config=agent_config,
                api_key=self.api_key,
                providers_config=self._providers_config,
                cache_enabled=self.cache_enabled,
            )
        return self._agents

    def get_agent(self, agent_id: str) -> BaseAgent:
        """Get agent by ID."""
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' not found")
        return self._agents[agent_id]

    def get_execution_order(self) -> list[list[str]]:
        """Get execution order using topological sort (Kahn's algorithm).

        Returns:
            List of waves, where each wave contains agent IDs that can run in parallel.
        """
        if self._config is None:
            raise ValueError("Config not loaded")

        agents = self._config.agents
        agent_ids = {a.id for a in agents}

        # Build adjacency list and in-degree count
        in_degree = {a.id: 0 for a in agents}
        graph: dict[str, list[str]] = {a.id: [] for a in agents}

        for agent in agents:
            for dep in agent.depends_on:
                if dep in agent_ids:
                    graph[dep].append(agent.id)
                    in_degree[agent.id] += 1

        # Kahn's algorithm
        result: list[list[str]] = []
        remaining = set(in_degree.keys())

        while remaining:
            # Find all agents with in_degree 0 (no unmet dependencies)
            ready = [aid for aid in remaining if in_degree[aid] == 0]

            if not ready:
                # Circular dependency - no agent has in_degree 0
                raise ValueError(
                    f"Circular dependency detected in agent configuration: {remaining}"
                )

            result.append(ready)

            # Remove processed agents and update in-degrees
            for aid in ready:
                remaining.remove(aid)
                for neighbor in graph[aid]:
                    in_degree[neighbor] -= 1

        return result

    def get_all_agent_ids(self) -> list[str]:
        """Get all agent IDs."""
        if self._config is None:
            raise ValueError("Config not loaded")
        return [a.id for a in self._config.agents]
