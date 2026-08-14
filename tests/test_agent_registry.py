"""Tests for AgentRegistry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from metadata_enricher.agents.registry import AgentRegistry
from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig


class FakeSchema:
    @property
    def name(self):
        return "fake"

    @property
    def version(self):
        return "1.0"

    @property
    def output_model(self):
        pass

    def validate_output(self, data):
        return data

    def normalize_field(self, name, value):
        return value

    def merge_agent_results(self, results):
        return {}

    def get_field_order(self):
        return []

    def get_required_fields(self):
        return ["titles"]


def make_config(num_agents=3):
    agents = [
        AgentConfig(
            id=f"a{i}",
            name=f"Agent {i}",
            fields=["titles"],
            prompt="Extract from {url}",
            provider="p1",
            model="test-model",
            depends_on=[f"a{i - 1}"] if i > 0 else [],
        )
        for i in range(num_agents)
    ]
    providers = [ProviderConfig(name="p1", base_url="http://localhost", api_key_env="TEST_KEY")]
    return PipelineConfig(
        schema_name="fake",
        agents=agents,
        providers=providers,
        default_provider="p1",
    )


def mock_factory(provider, model, temperature, max_tokens):
    m = MagicMock()
    m.model = model
    return m


@pytest.fixture
def schema():
    return FakeSchema()


def test_get_agent_by_id(schema):
    config = make_config(num_agents=3)
    registry = AgentRegistry(config=config, schema=schema, llm_factory=mock_factory)
    agent = registry.get_agent("a1")
    assert agent.name == "Agent 1"


def test_get_agent_unknown_raises(schema):
    config = make_config(num_agents=3)
    registry = AgentRegistry(config=config, schema=schema, llm_factory=mock_factory)
    with pytest.raises(KeyError, match="Agent 'nonexistent' not found"):
        registry.get_agent("nonexistent")


def test_registry_uses_llm_factory(schema):
    call_count = 0

    def counting_factory(provider, model, temperature, max_tokens):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.model = model
        return m

    config = make_config(num_agents=3)
    AgentRegistry(config=config, schema=schema, llm_factory=counting_factory)
    assert call_count == 3


def test_context_fields_reach_built_agent(schema):
    """AgentConfig.context_fields must actually be wired into the BaseAgent
    instance the registry builds, not just validated and discarded."""
    agents = [
        AgentConfig(
            id="a0", name="Agent 0", fields=["resource"], prompt="p", provider="p1",
            model="test-model",
        ),
        AgentConfig(
            id="a1", name="Agent 1", fields=["rights"], prompt="p", provider="p1",
            model="test-model", depends_on=["a0"], context_fields=["resource"],
        ),
    ]
    providers = [ProviderConfig(name="p1", base_url="http://localhost", api_key_env="TEST_KEY")]
    config = PipelineConfig(schema_name="fake", agents=agents, providers=providers, default_provider="p1")
    registry = AgentRegistry(config=config, schema=schema, llm_factory=mock_factory)
    agent = registry.get_agent("a1")
    assert agent._context_fields == ["resource"]  # noqa: SLF001


def test_dependency_graph(schema):
    config = make_config(num_agents=3)
    registry = AgentRegistry(config=config, schema=schema, llm_factory=mock_factory)
    graph = registry.get_dependency_graph()
    assert graph == {
        "a0": [],
        "a1": ["a0"],
        "a2": ["a1"],
    }


def test_registry_unknown_provider_raises(schema):
    agents = [
        AgentConfig(
            id="bad_agent",
            name="Bad",
            fields=["titles"],
            prompt="test",
            provider="nonexistent",
            model="test-model",
        )
    ]
    providers = [ProviderConfig(name="p1", base_url="http://localhost", api_key_env="TEST_KEY")]
    with pytest.raises(ValidationError, match="references provider 'nonexistent'"):
        PipelineConfig(
            schema_name="fake",
            agents=agents,
            providers=providers,
            default_provider="p1",
        )
