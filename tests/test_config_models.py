"""Tests for config models (metadata_enricher.config.models).

ProviderConfig, AgentConfig, PipelineConfig — pure Pydantic data models.
"""

import pytest
from pydantic import ValidationError

from metadata_enricher.config.models import (
    AgentConfig,
    PipelineConfig,
    ProviderConfig,
)


# ──────────────────────────────────────────────
# ProviderConfig
# ──────────────────────────────────────────────


class TestProviderConfig:
    """ProviderConfig: LLM provider connection settings."""

    def test_minimal(self):
        """Minimal creation with required fields only."""
        p = ProviderConfig(name="opencode", api_key_env="OPENCODE_API_KEY")
        assert p.name == "opencode"
        assert p.api_key_env == "OPENCODE_API_KEY"
        assert p.base_url is None
        assert p.default is False
        assert p.seed is None

    def test_all_fields(self):
        """All fields provided."""
        p = ProviderConfig(
            name="zai-coding-plan",
            base_url="https://api.z.ai/api/coding/paas/v4",
            api_key_env="ZAI_API_KEY",
            default=True,
            seed=42,
        )
        assert p.name == "zai-coding-plan"
        assert p.base_url == "https://api.z.ai/api/coding/paas/v4"
        assert p.api_key_env == "ZAI_API_KEY"
        assert p.default is True
        assert p.seed == 42

    def test_rejects_unknown_fields(self):
        """extra='forbid' — unknown fields raise ValidationError."""
        with pytest.raises(ValidationError):
            ProviderConfig(name="test", api_key_env="X", unknown="bad")

    def test_name_min_length(self):
        """name must be at least 1 character."""
        with pytest.raises(ValidationError):
            ProviderConfig(name="", api_key_env="X")


# ──────────────────────────────────────────────
# AgentConfig
# ──────────────────────────────────────────────


class TestAgentConfig:
    """AgentConfig: single agent definition."""

    def test_minimal(self):
        """Minimal creation with required fields only."""
        a = AgentConfig(
            id="core_metadata",
            name="Core Metadata Extractor",
            fields=["resource", "titles"],
            prompt="Eres un agente experto...",
            provider="opencode",
        )
        assert a.id == "core_metadata"
        assert a.name == "Core Metadata Extractor"
        assert a.fields == ["resource", "titles"]
        assert a.prompt == "Eres un agente experto..."
        assert a.provider == "opencode"
        assert a.description == ""
        assert a.model is None
        assert a.temperature == 0.0
        assert a.max_tokens is None
        assert a.depends_on == []
        assert a.use_chain_of_thought is False
        assert a.system_prompt is None

    def test_all_fields(self):
        """All fields provided with realistic values from andrea_v3.json."""
        a = AgentConfig(
            id="creators_publishers",
            name="Creators and Publishers",
            description="Extrae los creadores y editores del recurso.",
            fields=["creators", "publishers"],
            prompt="Eres un agente experto en identificacion...",
            system_prompt="Sistema: sigue las reglas de afiliacion.",
            provider="opencode",
            model="deepseek-v4-flash",
            temperature=0.2,
            max_tokens=4096,
            depends_on=["core_metadata"],
            use_chain_of_thought=True,
        )
        assert a.id == "creators_publishers"
        assert a.name == "Creators and Publishers"
        assert a.description == "Extrae los creadores y editores del recurso."
        assert a.fields == ["creators", "publishers"]
        assert a.prompt == "Eres un agente experto en identificacion..."
        assert a.system_prompt == "Sistema: sigue las reglas de afiliacion."
        assert a.provider == "opencode"
        assert a.model == "deepseek-v4-flash"
        assert a.temperature == 0.2
        assert a.max_tokens == 4096
        assert a.depends_on == ["core_metadata"]
        assert a.use_chain_of_thought is True

    def test_rejects_unknown_fields(self):
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            AgentConfig(
                id="x",
                name="x",
                fields=["f"],
                prompt="p",
                provider="p",
                unknown="bad",
            )

    def test_fields_min_length(self):
        """fields must have at least 1 element."""
        with pytest.raises(ValidationError):
            AgentConfig(
                id="x",
                name="x",
                fields=[],
                prompt="p",
                provider="p",
            )

    def test_prompt_min_length(self):
        """prompt must be at least 1 character."""
        with pytest.raises(ValidationError):
            AgentConfig(
                id="x",
                name="x",
                fields=["f"],
                prompt="",
                provider="p",
            )

    def test_id_min_length(self):
        """id must be at least 1 character."""
        with pytest.raises(ValidationError):
            AgentConfig(
                id="",
                name="x",
                fields=["f"],
                prompt="p",
                provider="p",
            )

    def test_name_not_empty(self):
        """name can be empty string (no min_length constraint)."""
        a = AgentConfig(id="x", name="", fields=["f"], prompt="p", provider="p")
        assert a.name == ""

    def test_depends_on_defaults_empty(self):
        """depends_on defaults to [] when not provided."""
        a = AgentConfig(id="x", name="x", fields=["f"], prompt="p", provider="p")
        assert a.depends_on == []

    def test_use_chain_of_thought_defaults_false(self):
        """use_chain_of_thought defaults to False."""
        a = AgentConfig(id="x", name="x", fields=["f"], prompt="p", provider="p")
        assert a.use_chain_of_thought is False

    def test_temperature_defaults_zero(self):
        """temperature defaults to 0.0."""
        a = AgentConfig(id="x", name="x", fields=["f"], prompt="p", provider="p")
        assert a.temperature == 0.0

    def test_max_tokens_none_by_default(self):
        """max_tokens defaults to None."""
        a = AgentConfig(id="x", name="x", fields=["f"], prompt="p", provider="p")
        assert a.max_tokens is None


# ──────────────────────────────────────────────
# PipelineConfig
# ──────────────────────────────────────────────


class TestPipelineConfig:
    """PipelineConfig: full pipeline with agents and providers."""

    # -- minimal / happy path -----------------------------------

    def test_minimal(self):
        """Minimal pipeline with 1 agent and 1 provider."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(
                    id="core_metadata",
                    name="Core",
                    fields=["resource"],
                    prompt="Prompt A",
                    provider="opencode",
                ),
            ],
            providers=[
                ProviderConfig(name="opencode", api_key_env="OPENCODE_API_KEY"),
            ],
        )
        assert p.schema_name == "datacite-4.6"
        assert len(p.agents) == 1
        assert len(p.providers) == 1
        assert p.default_provider is None
        assert p.strategies == {}
        assert p.max_workers == 4
        assert p.enable_identifier_enrichment is False
        assert p.enable_content_fetch is False
        assert p.validate_pids is True
        assert p.validate_pids_live is True

    def test_identifier_enrichment_and_pid_validation_overrides(self):
        """Both PID-validation flags and identifier enrichment can be toggled."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
            enable_identifier_enrichment=True,
            validate_pids=False,
            validate_pids_live=False,
        )
        assert p.enable_identifier_enrichment is True
        assert p.validate_pids is False
        assert p.validate_pids_live is False

    def test_content_fetch_override(self):
        """enable_content_fetch defaults off (no cost/behavior change for
        existing users) and can be explicitly opted into, same pattern as
        enable_identifier_enrichment."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
            enable_content_fetch=True,
        )
        assert p.enable_content_fetch is True

    def test_max_workers_override(self):
        """max_workers can be tuned down for tightly rate-limited providers."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
            max_workers=1,
        )
        assert p.max_workers == 1

    def test_max_workers_rejects_zero(self):
        """max_workers must be >= 1 — 0 or negative concurrency makes no sense."""
        with pytest.raises(ValidationError):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
                max_workers=0,
            )

    def test_full_config(self):
        """Full pipeline matching andrea_v3-like structure."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(
                    id="core_metadata",
                    name="Core Metadata Extractor",
                    fields=["resource", "titles", "descriptions"],
                    prompt="Eres un agente...",
                    provider="opencode",
                    temperature=0.2,
                    use_chain_of_thought=True,
                ),
                AgentConfig(
                    id="creators_publishers",
                    name="Creators and Publishers",
                    fields=["creators", "publishers"],
                    prompt="Identifica creadores...",
                    provider="opencode",
                    temperature=0.0,
                    depends_on=["core_metadata"],
                    use_chain_of_thought=True,
                ),
                AgentConfig(
                    id="media_files",
                    name="Media Files",
                    fields=["media_files"],
                    prompt="Describe archivos...",
                    provider="zai-coding-plan",
                    temperature=0.2,
                    depends_on=["creators_publishers"],
                ),
            ],
            providers=[
                ProviderConfig(
                    name="opencode",
                    base_url="https://opencode.ai/zen/go/v1",
                    api_key_env="OPENCODE_API_KEY",
                    default=True,
                ),
                ProviderConfig(
                    name="zai-coding-plan",
                    base_url="https://api.z.ai/api/coding/paas/v4",
                    api_key_env="ZAI_API_KEY",
                ),
            ],
            default_provider="opencode",
            strategies={"context": "accumulative"},
        )
        assert p.schema_name == "datacite-4.6"
        assert len(p.agents) == 3
        assert len(p.providers) == 2
        assert p.default_provider == "opencode"
        assert p.strategies == {"context": "accumulative"}
        assert p.agents[0].id == "core_metadata"
        assert p.agents[2].depends_on == ["creators_publishers"]

    # -- default_provider validation ----------------------------

    def test_default_provider_valid(self):
        """default_provider matches a provider name — valid."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
            default_provider="p1",
        )
        assert p.default_provider == "p1"

    def test_default_provider_invalid_raises(self):
        """default_provider does not exist in providers list — raises ValueError."""
        with pytest.raises(ValueError, match="default_provider.*not found"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="p1",
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
                default_provider="nonexistent",
            )

    # -- agent.provider validation ------------------------------

    def test_agent_provider_must_exist(self):
        """Agent references a provider not in the list."""
        with pytest.raises(ValueError, match="provider.*not in providers"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="missing_provider",
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    def test_agent_provider_exists_valid(self):
        """Agent references a provider that exists — valid."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(
                    id="a1",
                    name="A1",
                    fields=["f1"],
                    prompt="p",
                    provider="p1",
                ),
                AgentConfig(
                    id="a2",
                    name="A2",
                    fields=["f2"],
                    prompt="p",
                    provider="p2",
                ),
            ],
            providers=[
                ProviderConfig(name="p1", api_key_env="K1"),
                ProviderConfig(name="p2", api_key_env="K2"),
            ],
        )
        assert len(p.agents) == 2
        assert len(p.providers) == 2

    # -- depends_on validation ----------------------------------

    def test_depends_on_valid(self):
        """depends_on references existing agent IDs — valid."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
                AgentConfig(
                    id="a2",
                    name="A2",
                    fields=["f2"],
                    prompt="p",
                    provider="p1",
                    depends_on=["a1"],
                ),
                AgentConfig(
                    id="a3",
                    name="A3",
                    fields=["f3"],
                    prompt="p",
                    provider="p1",
                    depends_on=["a1", "a2"],
                ),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
        )
        assert p.agents[2].depends_on == ["a1", "a2"]

    def test_depends_on_nonexistent_raises(self):
        """depends_on references a non-existent agent ID — raises ValueError."""
        with pytest.raises(ValueError, match="depends_on.*not a known agent"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="p1",
                    ),
                    AgentConfig(
                        id="a2",
                        name="A2",
                        fields=["f2"],
                        prompt="p",
                        provider="p1",
                        depends_on=["nonexistent"],
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    # -- duplicate agent IDs ------------------------------------

    def test_duplicate_agent_id_raises(self):
        """Two agents with the same ID — raises ValueError."""
        with pytest.raises(ValueError, match="duplicate agent"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(id="dup", name="A1", fields=["f1"], prompt="p", provider="p1"),
                    AgentConfig(id="dup", name="A2", fields=["f2"], prompt="p", provider="p1"),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    # -- min_length constraints ---------------------------------

    def test_empty_agents_raises(self):
        """agents list must have at least 1 element."""
        with pytest.raises(ValidationError):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    def test_empty_providers_raises(self):
        """providers list must have at least 1 element."""
        with pytest.raises(ValidationError):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="p1",
                    ),
                ],
                providers=[],
            )

    def test_schema_name_min_length(self):
        """schema_name must be at least 1 character."""
        with pytest.raises(ValidationError):
            PipelineConfig(
                schema_name="",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="p1",
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    # -- strategies ---------------------------------------------

    def test_strategies_empty_default(self):
        """strategies defaults to empty dict."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
        )
        assert p.strategies == {}

    def test_strategies_with_values(self):
        """strategies accepts arbitrary key-value pairs."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
            strategies={"context": "accumulative", "retry": "exponential"},
        )
        assert p.strategies["context"] == "accumulative"
        assert p.strategies["retry"] == "exponential"

    # -- rejection of unknown fields ----------------------------

    def test_rejects_unknown_fields(self):
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="p1",
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
                unknown_key="bad",
            )

    # -- multiple validation errors -----------------------------

    def test_multiple_invalid_refs_all_reported(self):
        """Multiple agents with invalid provider refs — first one triggers error."""
        with pytest.raises(ValueError, match="provider.*not in providers"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="bad1",
                    ),
                    AgentConfig(
                        id="a2",
                        name="A2",
                        fields=["f2"],
                        prompt="p",
                        provider="bad2",
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )
