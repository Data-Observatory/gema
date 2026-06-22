"""Orchestrator for wave-based parallel agent execution with topological sorting."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from metadata_enricher.agents.registry import AgentRegistry
from metadata_enricher.types import AgentResult, ResourceDescription, TokenUsage

logger = logging.getLogger(__name__)


class Orchestrator:
    """Executes agents in topologically sorted parallel waves.

    Uses Kahn's algorithm to compute execution waves from agent dependencies.
    Agents within the same wave run concurrently via ThreadPoolExecutor.
    Each wave completes before the next begins.
    """

    def __init__(self, registry: AgentRegistry, max_workers: int = 4) -> None:
        self._registry = registry
        self._max_workers = max_workers

    def _compute_waves(self) -> list[list[str]]:
        """Compute execution waves using Kahn's topological sort.

        Returns a list of waves, where each wave is a list of agent IDs
        that can run in parallel (no inter-dependencies within a wave).
        """
        graph = self._registry.get_dependency_graph()  # {agent_id: [dep_ids]}
        all_agents = [ac.id for ac in self._registry.get_agent_configs()]

        # Build reverse dependency map and in-degree count
        in_degree: dict[str, int] = {aid: 0 for aid in all_agents}
        dependents: dict[str, list[str]] = {aid: [] for aid in all_agents}

        for agent_id, deps in graph.items():
            in_degree[agent_id] = len(deps)
            for dep in deps:
                if dep in dependents:
                    dependents[dep].append(agent_id)

        # Kahn's algorithm — wave by wave
        waves: list[list[str]] = []
        remaining = set(all_agents)

        while remaining:
            # Find all nodes with in_degree 0 (no unmet dependencies)
            current_wave = [aid for aid in all_agents if aid in remaining and in_degree[aid] == 0]
            if not current_wave:
                # Cycle detected
                raise ValueError(f"Dependency cycle detected among agents: {sorted(remaining)}")
            waves.append(current_wave)
            for aid in current_wave:
                remaining.discard(aid)
                for dependent in dependents.get(aid, []):
                    in_degree[dependent] -= 1

        return waves

    def run(self, resource: ResourceDescription) -> list[AgentResult]:
        """Run all agents in topologically sorted parallel waves.

        Returns all AgentResults collected from every agent.
        """
        waves = self._compute_waves()
        all_results: list[AgentResult] = []

        for wave_idx, wave in enumerate(waves):
            logger.info("Executing wave %d/%d: %s", wave_idx + 1, len(waves), wave)

            if len(wave) == 1:
                # Single agent — no need for thread pool
                agent = self._registry.get_agent(wave[0])
                results = agent.run(resource)
                all_results.extend(results)
            else:
                # Multiple agents — run in parallel
                with ThreadPoolExecutor(max_workers=min(self._max_workers, len(wave))) as executor:
                    future_to_agent = {
                        executor.submit(self._registry.get_agent(aid).run, resource): aid
                        for aid in wave
                    }
                    for future in as_completed(future_to_agent):
                        aid = future_to_agent[future]
                        try:
                            results = future.result()
                            all_results.extend(results)
                        except Exception as e:
                            logger.error("Agent '%s' failed: %s", aid, e)
                            # Record error as AgentResult per field of the failed agent
                            agent = self._registry.get_agent(aid)
                            for field in agent.fields:
                                all_results.append(
                                    AgentResult(
                                        field_name=field,
                                        value=None,
                                        error=f"Agent execution failed: {e}",
                                        token_usage=TokenUsage(),
                                    )
                                )

        return all_results

    @property
    def registry(self) -> AgentRegistry:
        return self._registry
