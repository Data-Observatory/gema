"""Tests for Orchestrator wave-based parallel execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metadata_enricher.agents.base import BaseAgent
from metadata_enricher.agents.registry import AgentRegistry
from metadata_enricher.config.models import AgentConfig
from metadata_enricher.orchestrator import Orchestrator
from metadata_enricher.types import AgentResult, ResourceDescription, TokenUsage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_agent_config(id: str, depends_on: list[str] | None = None) -> AgentConfig:
    return AgentConfig(
        id=id,
        name=f"Agent {id}",
        fields=["titles"],
        prompt="Test {url}",
        provider="p1",
        model="test",
        depends_on=depends_on or [],
    )


def make_registry_mock(agent_ids_with_deps: list[tuple[str, list[str]]]) -> MagicMock:
    """Build a mock registry with given agent dependency structure."""
    configs = [make_agent_config(aid, deps) for aid, deps in agent_ids_with_deps]
    registry = MagicMock(spec=AgentRegistry)
    registry.get_agent_configs.return_value = configs
    registry.get_dependency_graph.return_value = {cfg.id: list(cfg.depends_on) for cfg in configs}
    agents: dict[str, MagicMock] = {}
    for cfg in configs:
        m = MagicMock(spec=BaseAgent)
        m.run.return_value = [
            AgentResult(field_name="titles", value=[{"x": 1}], token_usage=TokenUsage())
        ]
        m.fields = list(cfg.fields)
        agents[cfg.id] = m

    def get_agent(aid: str) -> MagicMock:
        return agents[aid]

    registry.get_agent.side_effect = get_agent
    return registry


def make_resource() -> ResourceDescription:
    return ResourceDescription(url="https://example.org/resource")


# ---------------------------------------------------------------------------
# Wave computation tests
# ---------------------------------------------------------------------------


class TestComputeWaves:
    """Orchestrator._compute_waves topological sort."""

    def test_compute_waves_linear(self) -> None:
        """Agents a→b→c produce waves [[a],[b],[c]]."""
        registry = make_registry_mock([("a", []), ("b", ["a"]), ("c", ["b"])])
        orch = Orchestrator(registry)
        waves = orch._compute_waves()
        assert waves == [["a"], ["b"], ["c"]]

    def test_compute_waves_parallel(self) -> None:
        """a,b independent, c depends on both → waves [[a,b],[c]]."""
        registry = make_registry_mock([("a", []), ("b", []), ("c", ["a", "b"])])
        orch = Orchestrator(registry)
        waves = orch._compute_waves()
        assert len(waves) == 2
        assert set(waves[0]) == {"a", "b"}
        assert waves[1] == ["c"]

    def test_compute_waves_independent(self) -> None:
        """Three agents with no deps → single wave [[a,b,c]]."""
        registry = make_registry_mock([("a", []), ("b", []), ("c", [])])
        orch = Orchestrator(registry)
        waves = orch._compute_waves()
        assert len(waves) == 1
        assert set(waves[0]) == {"a", "b", "c"}

    def test_compute_waves_cycle_raises(self) -> None:
        """a depends on b, b depends on a → ValueError."""
        registry = make_registry_mock([("a", ["b"]), ("b", ["a"])])
        orch = Orchestrator(registry)
        with pytest.raises(ValueError, match="Dependency cycle detected"):
            orch._compute_waves()


# ---------------------------------------------------------------------------
# Run execution tests
# ---------------------------------------------------------------------------


class TestRun:
    """Orchestrator.run integration with mocked agents."""

    def test_run_executes_all_agents(self) -> None:
        """All agents' run() is called and results are collected."""
        registry = make_registry_mock([("a", []), ("b", ["a"]), ("c", [])])
        orch = Orchestrator(registry)
        resource = make_resource()
        results = orch.run(resource)

        # Each agent was called
        registry.get_agent("a").run.assert_called_once_with(resource)
        registry.get_agent("b").run.assert_called_once_with(resource)
        registry.get_agent("c").run.assert_called_once_with(resource)

        # 3 agents × 1 field each = 3 results
        assert len(results) == 3

    def test_run_results_collected(self) -> None:
        """AgentResults from all agents are returned in the list."""
        registry = make_registry_mock([("x", []), ("y", [])])
        orch = Orchestrator(registry)
        resource = make_resource()
        results = orch.run(resource)

        assert len(results) == 2
        for r in results:
            assert r.field_name == "titles"
            assert r.value == [{"x": 1}]
            assert r.error is None

    def test_run_agent_failure_continues(self) -> None:
        """One agent raises; others still run and error is recorded."""
        agent_ids = [("good1", []), ("failing", []), ("good2", [])]
        registry = make_registry_mock(agent_ids)

        # Make the failing agent raise
        registry.get_agent("failing").run.side_effect = RuntimeError("LLM timeout")

        orch = Orchestrator(registry)
        resource = make_resource()
        results = orch.run(resource)

        # good1 and good2 still ran
        registry.get_agent("good1").run.assert_called_once_with(resource)
        registry.get_agent("good2").run.assert_called_once_with(resource)

        # 3 results from good agents + 1 error result for failing agent
        assert len(results) == 3

        # Verify error result
        error_results = [r for r in results if r.error is not None]
        assert len(error_results) == 1
        assert error_results[0].field_name == "titles"
        assert "LLM timeout" in error_results[0].error

        # Verify good results
        good_results = [r for r in results if r.error is None]
        assert len(good_results) == 2


# ---------------------------------------------------------------------------
# Hardcoded-agent-name guard
# ---------------------------------------------------------------------------


class TestNoHardcodedNames:
    """Ensure orchestrator does not reference specific agents by name."""

    def test_no_hardcoded_agent_names(self) -> None:
        """Orchestrator must not contain the string 'explorer'."""
        import inspect
        from metadata_enricher import orchestrator as orch_mod

        source = inspect.getsource(orch_mod)
        assert "explorer" not in source, (
            "Orchestrator contains hardcoded agent name 'explorer'. Use the registry API instead."
        )
