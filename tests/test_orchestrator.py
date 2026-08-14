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

        # Each agent was called, with whatever upstream_fields had
        # accumulated by the time its wave ran (empty dict for wave 1).
        for aid in ("a", "b", "c"):
            call = registry.get_agent(aid).run.call_args
            assert call.args[0] is resource
            assert isinstance(call.kwargs["upstream_fields"], dict)

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
        assert registry.get_agent("good1").run.call_args.args[0] is resource
        assert registry.get_agent("good2").run.call_args.args[0] is resource

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
# Cross-wave upstream_fields threading
# ---------------------------------------------------------------------------


def _capture_upstream_fields(mock_run: MagicMock, captured: list[dict]) -> None:
    """Wrap *mock_run*'s side_effect to snapshot (deep-copy) upstream_fields
    at call time. Orchestrator.run() passes the SAME mutable dict object to
    every wave, mutating it in place after each wave completes -- inspecting
    ``mock.call_args`` after run() returns would see the final, fully-
    mutated dict for every past call, not what that call actually received."""
    original_return = mock_run.return_value

    def side_effect(*args: object, **kwargs: object) -> object:
        captured.append(dict(kwargs.get("upstream_fields") or {}))
        return original_return

    mock_run.side_effect = side_effect


class TestUpstreamFieldsThreading:
    """Orchestrator.run() accumulates completed waves' fields and passes
    them into every subsequent wave's agent.run() call — the plumbing
    context_fields-declaring agents (e.g. rights_funding_citations) rely on."""

    def test_first_wave_gets_empty_upstream_fields(self) -> None:
        registry = make_registry_mock([("a", [])])
        seen: list[dict] = []
        _capture_upstream_fields(registry.get_agent("a").run, seen)
        orch = Orchestrator(registry)
        orch.run(make_resource())
        assert seen == [{}]

    def test_second_wave_sees_first_waves_successful_fields(self) -> None:
        registry = make_registry_mock([("a", []), ("b", ["a"])])
        registry.get_agent("a").run.return_value = [
            AgentResult(field_name="resource", value={"identifier": "x"}, token_usage=TokenUsage())
        ]
        seen: list[dict] = []
        _capture_upstream_fields(registry.get_agent("b").run, seen)
        orch = Orchestrator(registry)
        orch.run(make_resource())

        assert seen == [{"resource": {"identifier": "x"}}]

    def test_errored_upstream_field_is_omitted_not_none(self) -> None:
        """An upstream agent's error must never surface as
        upstream_fields[field] = None -- it must be entirely absent, so a
        downstream agent can't confuse "upstream said empty" with "upstream
        failed"."""
        registry = make_registry_mock([("a", []), ("b", ["a"])])
        registry.get_agent("a").run.return_value = [
            AgentResult(field_name="titles", value=None, error="boom", token_usage=TokenUsage())
        ]
        seen: list[dict] = []
        _capture_upstream_fields(registry.get_agent("b").run, seen)
        orch = Orchestrator(registry)
        orch.run(make_resource())

        assert "titles" not in seen[0]

    def test_upstream_fields_accumulate_across_more_than_one_prior_wave(self) -> None:
        """c depends on both a (wave 1) and b (wave 2) -- c must see fields
        from both, not just the immediately preceding wave."""
        registry = make_registry_mock([("a", []), ("b", ["a"]), ("c", ["a", "b"])])
        registry.get_agent("a").run.return_value = [
            AgentResult(field_name="resource", value={"id": "a"}, token_usage=TokenUsage())
        ]
        registry.get_agent("b").run.return_value = [
            AgentResult(field_name="publishers", value=[{"publisher_name": "X"}], token_usage=TokenUsage())
        ]
        seen: list[dict] = []
        _capture_upstream_fields(registry.get_agent("c").run, seen)
        orch = Orchestrator(registry)
        orch.run(make_resource())

        assert seen == [{"resource": {"id": "a"}, "publishers": [{"publisher_name": "X"}]}]


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
