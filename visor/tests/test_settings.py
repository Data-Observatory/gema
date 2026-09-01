"""Tests for visor.settings — local secrets file + os.environ injection."""

from __future__ import annotations

import os
import stat

import pytest

from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig
from visor.settings import (
    VisorSettings,
    addable_providers,
    all_provider_env_vars,
    apply_to_environ,
    load_settings,
    missing_required,
    missing_required_details,
    optional_env_vars,
    providers_using,
    required_env_vars,
    save_settings,
)


def make_pipeline_config(
    *provider_names_and_envs: tuple[str, str], used_by_agents: tuple[str, ...] | None = None
) -> PipelineConfig:
    """Build a PipelineConfig. By default every declared provider is also
    used by an agent (one agent per provider) — pass used_by_agents to
    declare providers that no agent actually references, exercising the
    'declared but unused' exclusion."""
    providers = [
        ProviderConfig(name=name, base_url="http://localhost", api_key_env=env)
        for name, env in provider_names_and_envs
    ]
    agent_provider_names = (
        list(used_by_agents) if used_by_agents is not None else [p.name for p in providers]
    )
    return PipelineConfig(
        schema_name="datacite-4.6",
        agents=[
            AgentConfig(
                id=f"a{i}",
                name=f"A{i}",
                fields=["titles"],
                prompt="x",
                provider=name,
            )
            for i, name in enumerate(agent_provider_names)
        ],
        providers=providers,
        default_provider=providers[0].name,
    )


class TestVisorSettingsRoundtrip:
    def test_save_then_load_roundtrips(self, tmp_path):
        path = tmp_path / "settings.json"
        original = VisorSettings(default_provider="zai", env={"ZAI_API_KEY": "secret-123"})
        save_settings(original, path=path)
        loaded = load_settings(path=path)
        assert loaded.default_provider == "zai"
        assert loaded.env == {"ZAI_API_KEY": "secret-123"}

    def test_load_missing_file_returns_empty_settings(self, tmp_path):
        loaded = load_settings(path=tmp_path / "nonexistent.json")
        assert loaded == VisorSettings()

    def test_load_corrupt_file_returns_empty_settings(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("not valid json{{{", encoding="utf-8")
        loaded = load_settings(path=path)
        assert loaded == VisorSettings()

    def test_load_non_dict_json_returns_empty_settings(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        loaded = load_settings(path=path)
        assert loaded == VisorSettings()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits don't apply on Windows")
    def test_save_restricts_permissions_to_owner(self, tmp_path):
        path = tmp_path / "settings.json"
        save_settings(VisorSettings(env={"K": "v"}), path=path)
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == stat.S_IRUSR | stat.S_IWUSR


class TestRequiredEnvVars:
    def test_derives_from_providers_actually_used_by_agents(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"), ("openai", "OPENAI_API_KEY"))
        assert required_env_vars(config) == ["OPENAI_API_KEY", "ZAI_API_KEY"]

    def test_excludes_providers_declared_but_not_used_by_any_agent(self):
        """Regression: agents.yaml commonly declares several available
        providers (zai-coding-plan, opencode, openai, anthropic) while every
        agent actually calls just one. A first live boot of visor/app.py
        against the real config surfaced exactly this — all 4 keys were
        wrongly demanded even though only zai-coding-plan is ever called."""
        config = make_pipeline_config(
            ("zai", "ZAI_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
            used_by_agents=("zai",),
        )
        assert required_env_vars(config) == ["ZAI_API_KEY"]

    def test_dedupes_shared_env_var(self):
        config = make_pipeline_config(("a", "SHARED_KEY"), ("b", "SHARED_KEY"))
        assert required_env_vars(config) == ["SHARED_KEY"]

    def test_optional_env_vars_are_orcid_only(self):
        assert optional_env_vars() == ["ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET"]


class TestAllProviderEnvVars:
    def test_includes_providers_not_used_by_any_agent(self):
        """The opposite of required_env_vars — Settings must offer a key
        input for opencode even if no agent is assigned to it yet, so
        switching an agent's provider later in the Agents tab doesn't leave
        no way to ever enter that provider's key."""
        config = make_pipeline_config(
            ("zai", "ZAI_API_KEY"), ("opencode", "OPENCODE_API_KEY"), used_by_agents=("zai",)
        )
        assert all_provider_env_vars(config) == ["OPENCODE_API_KEY", "ZAI_API_KEY"]

    def test_dedupes_shared_env_var(self):
        config = make_pipeline_config(("a", "SHARED_KEY"), ("b", "SHARED_KEY"))
        assert all_provider_env_vars(config) == ["SHARED_KEY"]


class TestProvidersUsing:
    def test_lists_agent_ids_assigned_to_the_matching_provider(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"), ("openai", "OPENAI_API_KEY"))
        assert providers_using(config, "ZAI_API_KEY") == ["a0"]
        assert providers_using(config, "OPENAI_API_KEY") == ["a1"]

    def test_empty_when_no_agent_uses_it(self):
        config = make_pipeline_config(
            ("zai", "ZAI_API_KEY"), ("opencode", "OPENCODE_API_KEY"), used_by_agents=("zai",)
        )
        assert providers_using(config, "OPENCODE_API_KEY") == []


class TestAddableProviders:
    """Settings' "Add a provider" picker offers exactly this list — see
    settings_page.py. Deliberately unit-tested here rather than via a full
    app boot: the real default config (config/agents.yaml) already
    declares every entry in the real pool (config/providers.yaml), so a
    click-through test can never actually exercise "a pool entry that's
    still addable" against it.
    """

    def test_excludes_already_declared_providers(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"))
        pool = [
            ProviderConfig(name="zai", base_url="http://a", api_key_env="ZAI_API_KEY"),
            ProviderConfig(name="groq", base_url="http://b", api_key_env="GROQ_API_KEY"),
        ]
        result = addable_providers(pool, config)
        assert [p.name for p in result] == ["groq"]

    def test_empty_when_pool_fully_covered(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"), ("groq", "GROQ_API_KEY"))
        pool = [
            ProviderConfig(name="zai", base_url="http://a", api_key_env="ZAI_API_KEY"),
            ProviderConfig(name="groq", base_url="http://b", api_key_env="GROQ_API_KEY"),
        ]
        assert addable_providers(pool, config) == []

    def test_preserves_pool_entry_fields_for_autofill(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"))
        pool = [ProviderConfig(name="groq", base_url="https://api.groq.com/openai/v1", api_key_env="GROQ_API_KEY")]
        result = addable_providers(pool, config)
        assert result[0].base_url == "https://api.groq.com/openai/v1"
        assert result[0].api_key_env == "GROQ_API_KEY"

    def test_empty_pool_returns_empty(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"))
        assert addable_providers([], config) == []


class TestApplyToEnviron:
    def test_injects_saved_keys_into_os_environ(self, monkeypatch):
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        apply_to_environ(VisorSettings(env={"ZAI_API_KEY": "abc123"}))
        assert os.environ["ZAI_API_KEY"] == "abc123"

    def test_skips_empty_values(self, monkeypatch):
        monkeypatch.delenv("SOME_KEY", raising=False)
        apply_to_environ(VisorSettings(env={"SOME_KEY": ""}))
        assert "SOME_KEY" not in os.environ


class TestMissingRequired:
    def test_all_present_returns_empty(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"))
        settings = VisorSettings(env={"ZAI_API_KEY": "abc"})
        assert missing_required(config, settings) == []

    def test_missing_key_is_reported(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"))
        settings = VisorSettings()
        assert missing_required(config, settings) == ["ZAI_API_KEY"]

    def test_empty_string_value_counts_as_missing(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"))
        settings = VisorSettings(env={"ZAI_API_KEY": ""})
        assert missing_required(config, settings) == ["ZAI_API_KEY"]


class TestMissingRequiredDetails:
    def test_all_present_returns_empty(self):
        config = make_pipeline_config(("zai", "ZAI_API_KEY"))
        settings = VisorSettings(env={"ZAI_API_KEY": "abc"})
        assert missing_required_details(config, settings) == []

    def test_attributes_missing_key_to_its_provider_and_agents(self):
        config = make_pipeline_config(("openrouter", "OPENROUTER_API_KEY"))
        settings = VisorSettings()
        details = missing_required_details(config, settings)
        assert len(details) == 1
        assert details[0].api_key_env == "OPENROUTER_API_KEY"
        assert details[0].provider == "openrouter"
        assert details[0].agent_ids == ["a0"]

    def test_mixed_providers_reports_only_the_missing_one(self):
        """Switching one agent to a new provider (e.g. opencode) while
        others stay on the default must only call out the provider that's
        actually short a key -- this is what previously surfaced as a
        confusing flat env-var list with no indication of *why*."""
        config = make_pipeline_config(
            ("openrouter", "OPENROUTER_API_KEY"), ("opencode", "OPENCODE_API_KEY")
        )
        settings = VisorSettings(env={"OPENCODE_API_KEY": "sk-test"})
        details = missing_required_details(config, settings)
        assert len(details) == 1
        assert details[0].api_key_env == "OPENROUTER_API_KEY"
        assert details[0].provider == "openrouter"
        assert details[0].agent_ids == ["a0"]

    def test_groups_multiple_agents_on_the_same_missing_provider(self):
        config = make_pipeline_config(
            ("openrouter", "OPENROUTER_API_KEY"), used_by_agents=("openrouter", "openrouter")
        )
        settings = VisorSettings()
        details = missing_required_details(config, settings)
        assert len(details) == 1
        assert details[0].agent_ids == ["a0", "a1"]
