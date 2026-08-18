"""Orchestrator for wave-based parallel agent execution with topological sorting."""

from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

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
        # Accumulated across every completed wave (not just the immediately
        # prior one) -- an agent can depend on agents spread across more
        # than one earlier wave. Only successful (non-error) fields ever
        # land here; see BaseAgent.run()'s upstream_fields docstring for why
        # an errored upstream field is omitted rather than passed as None.
        upstream_fields: dict[str, Any] = {}

        for wave_idx, wave in enumerate(waves):
            logger.info("Executing wave %d/%d: %s", wave_idx + 1, len(waves), wave)
            wave_results: list[AgentResult] = []

            if len(wave) == 1:
                # Single agent — no need for thread pool
                agent = self._registry.get_agent(wave[0])
                wave_results.extend(agent.run(resource, upstream_fields=upstream_fields))
            else:
                # Multiple agents — run in parallel
                with ThreadPoolExecutor(max_workers=min(self._max_workers, len(wave))) as executor:
                    future_to_agent = {
                        # contextvars.copy_context() (a fresh one per
                        # submission -- the same Context object can't be
                        # entered concurrently on more than one thread)
                        # carries caller-set context, such as visor's
                        # per-run log-capture id (see
                        # visor/log_stream.py's activate_run), into this
                        # agent's own worker thread. Plain thread-locals
                        # don't cross thread boundaries on their own.
                        executor.submit(
                            contextvars.copy_context().run,
                            self._registry.get_agent(aid).run,
                            resource,
                            upstream_fields=upstream_fields,
                        ): aid
                        for aid in wave
                    }
                    for future in as_completed(future_to_agent):
                        aid = future_to_agent[future]
                        try:
                            wave_results.extend(future.result())
                        except Exception as e:
                            logger.error("Agent '%s' failed: %s", aid, e)
                            # Record error as AgentResult per field of the failed agent
                            agent = self._registry.get_agent(aid)
                            for field in agent.fields:
                                wave_results.append(
                                    AgentResult(
                                        field_name=field,
                                        value=None,
                                        error=f"Agent execution failed: {e}",
                                        token_usage=TokenUsage(),
                                    )
                                )

            all_results.extend(wave_results)
            for result in wave_results:
                if result.error is None:
                    upstream_fields[result.field_name] = result.value

        return all_results

    @property
    def registry(self) -> AgentRegistry:
        return self._registry
