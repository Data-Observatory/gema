"""Tests for config models (metadata_enricher.config.models).

ProviderConfig, AgentConfig, PipelineConfig — pure Pydantic data models.
"""

import pytest
from pydantic import ValidationError

from metadata_enricher.config.models import (
    AgentConfig,
    ModelOverride,
    PipelineConfig,
    ProviderConfig,
    find_model_override_elsewhere,
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

    def test_context_fields_defaults_empty(self):
        """context_fields defaults to [] when not provided."""
        a = AgentConfig(id="x", name="x", fields=["f"], prompt="p", provider="p")
        assert a.context_fields == []

    def test_context_fields_explicit(self):
        a = AgentConfig(
            id="x", name="x", fields=["f"], prompt="p", provider="p",
            depends_on=["core_metadata"], context_fields=["resource", "publishers"],
        )
        assert a.context_fields == ["resource", "publishers"]

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

    # -- context_fields cross-validation --------------------------

    def test_context_fields_from_direct_dependency_valid(self):
        """context_fields naming a field the direct depends_on agent
        actually produces — valid."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(
                    id="a1", name="A1", fields=["resource", "publishers"],
                    prompt="p", provider="p1",
                ),
                AgentConfig(
                    id="a2", name="A2", fields=["f2"], prompt="p", provider="p1",
                    depends_on=["a1"], context_fields=["resource", "publishers"],
                ),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
        )
        assert p.agents[1].context_fields == ["resource", "publishers"]

    def test_context_fields_from_transitive_dependency_valid(self):
        """context_fields naming a field produced by a depends_on ancestor
        more than one wave back — still valid, since Orchestrator.run()
        accumulates fields across every completed wave, not just the
        immediately preceding one."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["resource"], prompt="p", provider="p1"),
                AgentConfig(
                    id="a2", name="A2", fields=["f2"], prompt="p", provider="p1",
                    depends_on=["a1"],
                ),
                AgentConfig(
                    id="a3", name="A3", fields=["f3"], prompt="p", provider="p1",
                    depends_on=["a2"], context_fields=["resource"],
                ),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
        )
        assert p.agents[2].context_fields == ["resource"]

    def test_context_fields_unknown_field_raises(self):
        """context_fields names a field no depends_on ancestor produces --
        raises ValueError instead of silently injecting nothing at runtime."""
        with pytest.raises(ValueError, match="context_fields.*not produced by"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1", name="A1", fields=["resource"], prompt="p", provider="p1",
                    ),
                    AgentConfig(
                        id="a2", name="A2", fields=["f2"], prompt="p", provider="p1",
                        depends_on=["a1"], context_fields=["publishers"],
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    def test_context_fields_from_non_dependency_raises(self):
        """context_fields names a field produced by a real agent that is
        NOT a depends_on ancestor -- rejected, since Orchestrator.run()
        only guarantees fields from actual (transitive) dependencies are
        available before this agent's own wave."""
        with pytest.raises(ValueError, match="context_fields.*not produced by"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1", name="A1", fields=["resource"], prompt="p", provider="p1",
                    ),
                    AgentConfig(
                        id="unrelated", name="U", fields=["publishers"],
                        prompt="p", provider="p1",
                    ),
                    AgentConfig(
                        id="a2", name="A2", fields=["f2"], prompt="p", provider="p1",
                        depends_on=["a1"], context_fields=["publishers"],
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    def test_context_fields_without_depends_on_raises(self):
        """context_fields with no depends_on at all has no possible
        ancestor to produce anything -- raises."""
        with pytest.raises(ValueError, match="context_fields.*not produced by"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1", name="A1", fields=["f1"], prompt="p", provider="p1",
                        context_fields=["resource"],
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )

    # -- tools cross-validation -----------------------------------

    def test_tools_known_name_valid(self):
        """tools naming a real TOOL_REGISTRY entry — valid."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(
                    id="a1", name="A1", fields=["f1"], prompt="p", provider="p1",
                    tools=["lookup_organization"],
                ),
            ],
            providers=[ProviderConfig(name="p1", api_key_env="K")],
        )
        assert p.agents[0].tools == ["lookup_organization"]

    def test_tools_unknown_name_raises(self):
        """tools naming something not in TOOL_REGISTRY -- raises ValueError
        instead of silently doing nothing at runtime (BaseAgent only checks
        `if self._tools`, it never validates names against the registry)."""
        with pytest.raises(ValueError, match="tools.*not found in TOOL_REGISTRY"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1", name="A1", fields=["f1"], prompt="p", provider="p1",
                        tools=["not_a_real_tool"],
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

    # -- duplicate provider names --------------------------------

    def test_duplicate_provider_name_raises(self):
        """Two providers with the same name — raises ValueError. Unlike two
        providers sharing one api_key_env (legitimate: same account key,
        different base_urls), a duplicate *name* is never valid since
        agents and default_provider both reference a provider by name
        alone."""
        with pytest.raises(ValueError, match="duplicate provider names"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="dup"),
                ],
                providers=[
                    ProviderConfig(name="dup", api_key_env="K1"),
                    ProviderConfig(name="dup", api_key_env="K2"),
                ],
            )

    def test_shared_api_key_env_across_distinct_providers_is_allowed(self):
        """Two distinct providers sharing one api_key_env — not rejected,
        unlike a duplicate name above."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
                AgentConfig(id="a2", name="A2", fields=["f2"], prompt="p", provider="p2"),
            ],
            providers=[
                ProviderConfig(name="p1", api_key_env="SHARED_KEY"),
                ProviderConfig(name="p2", api_key_env="SHARED_KEY"),
            ],
        )
        assert [p_.name for p_ in p.providers] == ["p1", "p2"]

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


# ──────────────────────────────────────────────
# api_style / reasoning_effort (Responses-API opt-in)
# ──────────────────────────────────────────────


class TestApiStyleDefaults:
    """A provider/model that says nothing stays byte-for-byte on today's
    behavior -- api_style defaults to chat_completions everywhere."""

    def test_provider_defaults_to_chat_completions(self):
        p = ProviderConfig(name="opencode", api_key_env="OPENCODE_API_KEY")
        assert p.api_style == "chat_completions"
        assert p.reasoning_effort is None

    def test_model_override_defaults_to_none(self):
        """None on a ModelOverride means 'inherit from the provider', not
        'chat_completions' -- the provider-level field is what carries the
        actual resolved default."""
        override = ModelOverride(model="deepseek-v4-flash")
        assert override.api_style is None
        assert override.reasoning_effort is None

    def test_rejects_invalid_api_style(self):
        with pytest.raises(ValidationError):
            ProviderConfig(name="opencode", api_key_env="K", api_style="carrier_pigeon")

    def test_rejects_invalid_reasoning_effort(self):
        with pytest.raises(ValidationError):
            ProviderConfig(name="opencode", api_key_env="K", reasoning_effort="ludicrous")

    def test_agent_reasoning_effort_defaults_to_none(self):
        a = AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1")
        assert a.reasoning_effort is None


class TestEffectiveApiStyle:
    """ProviderConfig.effective_api_style — same 2-level cascade shape as
    effective_max_workers: provider default -> per-model override, model
    matched only within this provider's own model_overrides."""

    def test_no_override_returns_provider_default(self):
        p = ProviderConfig(name="opencode", api_key_env="K")
        assert p.effective_api_style("deepseek-v4-flash") == "chat_completions"

    def test_provider_level_responses_applies_to_every_model(self):
        p = ProviderConfig(name="opencode", api_key_env="K", api_style="responses")
        assert p.effective_api_style("anything") == "responses"

    def test_model_override_wins_over_provider_default(self):
        p = ProviderConfig(
            name="opencode",
            api_key_env="K",
            model_overrides=[
                ModelOverride(model="muse-spark-1.3-contributor", api_style="responses"),
            ],
        )
        assert p.effective_api_style("muse-spark-1.3-contributor") == "responses"
        assert p.effective_api_style("deepseek-v4-flash") == "chat_completions"

    def test_model_name_not_matched_under_different_provider(self):
        """The same model name declared under provider A's model_overrides
        must not leak into provider B's resolution -- each ProviderConfig
        only ever scans its own model_overrides list."""
        p_a = ProviderConfig(
            name="provider-a",
            api_key_env="K",
            model_overrides=[ModelOverride(model="shared-model-name", api_style="responses")],
        )
        p_b = ProviderConfig(name="provider-b", api_key_env="K")
        assert p_a.effective_api_style("shared-model-name") == "responses"
        assert p_b.effective_api_style("shared-model-name") == "chat_completions"


class TestEffectiveReasoningEffort:
    """ProviderConfig.effective_reasoning_effort — 3-level cascade: hardcoded
    conservative default -> provider default -> per-model override."""

    def test_no_override_returns_hardcoded_default(self):
        p = ProviderConfig(name="opencode", api_key_env="K")
        assert p.effective_reasoning_effort("muse-spark-1.3-contributor") == "medium"

    def test_provider_level_default_applies_to_every_model(self):
        p = ProviderConfig(name="opencode", api_key_env="K", reasoning_effort="medium")
        assert p.effective_reasoning_effort("anything") == "medium"

    def test_model_override_wins_over_provider_default(self):
        p = ProviderConfig(
            name="opencode",
            api_key_env="K",
            reasoning_effort="medium",
            model_overrides=[
                ModelOverride(model="muse-spark-1.3-contributor", reasoning_effort="high"),
            ],
        )
        assert p.effective_reasoning_effort("muse-spark-1.3-contributor") == "high"
        assert p.effective_reasoning_effort("some-other-model") == "medium"

    def test_provider_default_hint_explicit_opt_out(self):
        """reasoning_effort='provider_default' is a real, distinct value --
        it means 'omit the reasoning block entirely', not 'unset'."""
        p = ProviderConfig(
            name="opencode",
            api_key_env="K",
            model_overrides=[
                ModelOverride(model="m", reasoning_effort="provider_default"),
            ],
        )
        assert p.effective_reasoning_effort("m") == "provider_default"


class TestFindModelOverrideElsewhere:
    """find_model_override_elsewhere -- the misconfiguration-detection
    helper visor's Agents tab warns from at save time. Generic over any
    model/provider pair, not tied to any one real model."""

    def test_none_when_assigned_provider_already_has_override(self):
        providers = [
            ProviderConfig(
                name="p1",
                api_key_env="K",
                model_overrides=[ModelOverride(model="m", api_style="responses")],
            ),
        ]
        assert find_model_override_elsewhere(providers, "m", "p1") is None

    def test_none_when_no_provider_has_an_override(self):
        providers = [ProviderConfig(name="p1", api_key_env="K")]
        assert find_model_override_elsewhere(providers, "m", "p1") is None

    def test_finds_other_provider_with_the_override(self):
        providers = [
            ProviderConfig(name="p1", api_key_env="K"),
            ProviderConfig(
                name="p2",
                api_key_env="K",
                model_overrides=[ModelOverride(model="m", api_style="responses")],
            ),
        ]
        assert find_model_override_elsewhere(providers, "m", "p1") == "p2"

    def test_unknown_assigned_provider_still_checks_others(self):
        """agent.provider not (yet) matching any real provider (e.g. a
        stale value from an in-progress edit) must not crash the check --
        it's just treated as 'this provider has no override'."""
        providers = [
            ProviderConfig(
                name="p2",
                api_key_env="K",
                model_overrides=[ModelOverride(model="m", api_style="responses")],
            ),
        ]
        assert find_model_override_elsewhere(providers, "m", "not-a-real-provider") == "p2"

    def test_warns_even_when_assigned_provider_has_an_unrelated_override_entry(self):
        """Regression (found on review): a provider carrying *an* entry for
        this model that only sets an unrelated field (max_workers here)
        must not be mistaken for "already covered" -- api_style still
        cascades down to that provider's own plain default (chat_completions
        here), which genuinely differs from what another provider's
        api_style override would give."""
        providers = [
            ProviderConfig(
                name="p1",
                api_key_env="K",
                model_overrides=[ModelOverride(model="m", max_workers=2)],
            ),
            ProviderConfig(
                name="p2",
                api_key_env="K",
                model_overrides=[ModelOverride(model="m", api_style="responses")],
            ),
        ]
        assert find_model_override_elsewhere(providers, "m", "p1") == "p2"

    def test_none_when_assigned_provider_resolves_to_the_same_value(self):
        """Two providers can each declare their own api_style override for
        the same model and agree -- no real mismatch, must not warn."""
        providers = [
            ProviderConfig(
                name="p1",
                api_key_env="K",
                model_overrides=[ModelOverride(model="m", api_style="responses")],
            ),
            ProviderConfig(
                name="p2",
                api_key_env="K",
                model_overrides=[ModelOverride(model="m", api_style="responses")],
            ),
        ]
        assert find_model_override_elsewhere(providers, "m", "p1") is None

    def test_finds_reasoning_effort_mismatch_too(self):
        providers = [
            ProviderConfig(name="p1", api_key_env="K"),
            ProviderConfig(
                name="p2",
                api_key_env="K",
                reasoning_effort="medium",
                model_overrides=[ModelOverride(model="m", reasoning_effort="high")],
            ),
        ]
        assert find_model_override_elsewhere(providers, "m", "p1") == "p2"


class TestModelOverridesValidation:
    """PipelineConfig-level validation added alongside api_style/
    reasoning_effort -- duplicate model_overrides entries for the same model
    within one provider are ambiguous (which one wins?) and were previously
    silently allowed (last-one-wins) even for max_workers; now rejected."""

    def test_duplicate_model_override_within_one_provider_rejected(self):
        with pytest.raises(ValueError, match="duplicate model_overrides"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
                ],
                providers=[
                    ProviderConfig(
                        name="p1",
                        api_key_env="K",
                        model_overrides=[
                            ModelOverride(model="dup-model", api_style="responses"),
                            ModelOverride(model="dup-model", max_workers=2),
                        ],
                    ),
                ],
            )

    def test_same_model_name_different_providers_not_a_duplicate(self):
        """Duplicate-detection is scoped per-provider, matching every other
        model_overrides rule in this file."""
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[
                ProviderConfig(
                    name="p1",
                    api_key_env="K1",
                    model_overrides=[ModelOverride(model="shared-name")],
                ),
                ProviderConfig(
                    name="p2",
                    api_key_env="K2",
                    model_overrides=[ModelOverride(model="shared-name")],
                ),
            ],
        )
        assert len(p.providers) == 2

    def test_distinct_models_same_provider_not_duplicates(self):
        p = PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
            ],
            providers=[
                ProviderConfig(
                    name="p1",
                    api_key_env="K",
                    model_overrides=[
                        ModelOverride(model="model-a"),
                        ModelOverride(model="model-b"),
                    ],
                ),
            ],
        )
        assert len(p.providers[0].model_overrides) == 2


class TestAgentReasoningEffortWarning:
    """agent.reasoning_effort on a chat_completions-resolved agent warns but
    never raises -- must not break scripts/compare_models.py's in-place
    agent.model rewrites when swapping between models for comparison."""

    def test_warns_when_agent_resolves_to_chat_completions(self, caplog):
        with caplog.at_level("WARNING"):
            p = PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="p1",
                        model="deepseek-v4-flash",
                        reasoning_effort="medium",
                    ),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )
        assert p.agents[0].reasoning_effort == "medium"
        assert any("reasoning_effort" in record.message for record in caplog.records)
        assert any("chat_completions" in record.message for record in caplog.records)

    def test_no_warning_when_agent_resolves_to_responses(self, caplog):
        with caplog.at_level("WARNING"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(
                        id="a1",
                        name="A1",
                        fields=["f1"],
                        prompt="p",
                        provider="p1",
                        model="muse-spark-1.3-contributor",
                        reasoning_effort="low",
                    ),
                ],
                providers=[
                    ProviderConfig(
                        name="p1",
                        api_key_env="K",
                        model_overrides=[
                            ModelOverride(
                                model="muse-spark-1.3-contributor", api_style="responses"
                            ),
                        ],
                    ),
                ],
            )
        assert not any("reasoning_effort" in record.message for record in caplog.records)

    def test_no_warning_when_reasoning_effort_unset(self, caplog):
        with caplog.at_level("WARNING"):
            PipelineConfig(
                schema_name="datacite-4.6",
                agents=[
                    AgentConfig(id="a1", name="A1", fields=["f1"], prompt="p", provider="p1"),
                ],
                providers=[ProviderConfig(name="p1", api_key_env="K")],
            )
        assert len(caplog.records) == 0
