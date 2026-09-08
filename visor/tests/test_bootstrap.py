"""Tests for visor.bootstrap — config resolution, incl. frozen-build seeding."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import visor.bootstrap as bootstrap
from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig

_REAL_AGENTS_YAML = Path(__file__).resolve().parent.parent.parent / "config" / "agents.yaml"


class TestBundledConfigPath:
    def test_none_when_not_frozen(self, monkeypatch):
        monkeypatch.delattr("sys.frozen", raising=False)
        assert bootstrap.bundled_config_path() is None

    def test_returns_path_when_frozen_and_file_exists(self, monkeypatch, tmp_path):
        bundled_dir = tmp_path / "visor_default_config"
        bundled_dir.mkdir()
        (bundled_dir / "agents.yaml").write_text("schema_name: x", encoding="utf-8")

        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

        result = bootstrap.bundled_config_path()
        assert result == bundled_dir / "agents.yaml"

    def test_none_when_frozen_but_bundled_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
        assert bootstrap.bundled_config_path() is None


class TestResolveConfigPath:
    def test_returns_find_config_result_when_available(self, monkeypatch, tmp_path):
        real_config = tmp_path / "real_agents.yaml"
        real_config.write_text("schema_name: x", encoding="utf-8")
        monkeypatch.setattr(bootstrap, "find_config", lambda: real_config)
        assert bootstrap.resolve_config_path() == real_config

    def test_seeds_user_config_from_bundled_when_not_found_and_frozen(self, monkeypatch, tmp_path):
        def _raise():
            raise FileNotFoundError("no config found")

        bundled = tmp_path / "bundled_agents.yaml"
        bundled.write_text("schema_name: seeded", encoding="utf-8")
        target = tmp_path / "user_config" / "agents.yaml"

        monkeypatch.setattr(bootstrap, "find_config", _raise)
        monkeypatch.setattr(bootstrap, "bundled_config_path", lambda: bundled)

        result = bootstrap.resolve_config_path(user_config_path=target)

        assert result == target
        assert target.read_text(encoding="utf-8") == "schema_name: seeded"

    def test_never_writes_back_into_bundled_source(self, monkeypatch, tmp_path):
        """The bundled file is read-only source material — only the user's
        writable copy is created/modified."""

        def _raise():
            raise FileNotFoundError("no config found")

        bundled = tmp_path / "bundled_agents.yaml"
        bundled.write_text("schema_name: original", encoding="utf-8")
        original_mtime = bundled.stat().st_mtime_ns

        monkeypatch.setattr(bootstrap, "find_config", _raise)
        monkeypatch.setattr(bootstrap, "bundled_config_path", lambda: bundled)

        bootstrap.resolve_config_path(user_config_path=tmp_path / "user" / "agents.yaml")

        assert bundled.read_text(encoding="utf-8") == "schema_name: original"
        assert bundled.stat().st_mtime_ns == original_mtime

    def test_reraises_when_not_frozen_and_nothing_found(self, monkeypatch):
        def _raise():
            raise FileNotFoundError("no config found")

        monkeypatch.setattr(bootstrap, "find_config", _raise)
        monkeypatch.setattr(bootstrap, "bundled_config_path", lambda: None)

        with pytest.raises(FileNotFoundError):
            bootstrap.resolve_config_path()


class TestApplyExternalUserProviderOverrides:
    """The pure transform itself -- see TestLoadPipelineConfig for proof
    that load_pipeline_config() actually applies it to whatever config it
    resolves, regardless of source (found directly vs. seeded)."""

    def _sample_yaml(self) -> str:
        return yaml.safe_dump(
            {
                "providers": [
                    {"name": "opencode", "api_key_env": "OPENCODE_API_KEY", "default": True},
                    {"name": "openrouter", "api_key_env": "OPENROUTER_API_KEY", "default": False},
                    {"name": "openai", "api_key_env": "OPENAI_API_KEY"},
                ],
                "default_provider": "opencode",
                "agents": [
                    {
                        "id": "a0",
                        "provider": "opencode",
                        "model": "deepseek-v4-flash",
                        "extra_body": {"thinking": {"type": "disabled"}},
                    },
                    {"id": "a1", "provider": "openai", "model": "gpt-x"},
                ],
            }
        )

    def test_swaps_opencode_agents_to_openrouter(self):
        result = yaml.safe_load(
            bootstrap.apply_external_user_provider_overrides(self._sample_yaml())
        )
        opencode_agent = next(a for a in result["agents"] if a["id"] == "a0")
        assert opencode_agent["provider"] == "openrouter"
        assert opencode_agent["model"] == "~deepseek/deepseek-v4-flash-latest"
        assert opencode_agent["extra_body"] == {"reasoning": {"enabled": False}}

    def test_leaves_agents_on_other_providers_untouched(self):
        result = yaml.safe_load(
            bootstrap.apply_external_user_provider_overrides(self._sample_yaml())
        )
        openai_agent = next(a for a in result["agents"] if a["id"] == "a1")
        assert openai_agent["provider"] == "openai"
        assert openai_agent["model"] == "gpt-x"
        assert "extra_body" not in openai_agent

    def test_flips_provider_default_flags_and_default_provider(self):
        result = yaml.safe_load(
            bootstrap.apply_external_user_provider_overrides(self._sample_yaml())
        )
        by_name = {p["name"]: p for p in result["providers"]}
        assert by_name["opencode"]["default"] is False
        assert by_name["openrouter"]["default"] is True
        assert result["default_provider"] == "openrouter"

    def test_returns_input_unchanged_when_openrouter_provider_absent(self):
        raw = yaml.safe_dump(
            {
                "providers": [{"name": "opencode", "api_key_env": "OPENCODE_API_KEY"}],
                "default_provider": "opencode",
                "agents": [{"id": "a0", "provider": "opencode", "model": "deepseek-v4-flash"}],
            }
        )
        assert bootstrap.apply_external_user_provider_overrides(raw) == raw

    def test_non_mapping_yaml_returned_unchanged(self):
        assert bootstrap.apply_external_user_provider_overrides("schema_name: seeded") == (
            "schema_name: seeded"
        )

    def test_real_bundled_config_transforms_cleanly_and_still_validates(self):
        """End-to-end confidence check against the actual committed
        config/agents.yaml, not just a hand-built sample."""
        raw = _REAL_AGENTS_YAML.read_text(encoding="utf-8")
        transformed = bootstrap.apply_external_user_provider_overrides(raw)

        config = PipelineConfig(**yaml.safe_load(transformed))
        assert config.default_provider == "openrouter"
        for agent in config.agents:
            assert agent.provider == "openrouter"
            assert agent.model == "~deepseek/deepseek-v4-flash-latest"
            assert agent.extra_body == {"reasoning": {"enabled": False}}


class TestRestoreTestingProviderIfKeyAvailable:
    """The undo half of the openrouter swap -- confirmed 2026-09-08: without
    this, a session with real opencode access still got silently rerouted
    through openrouter's model alias, which doesn't reliably suppress
    thinking-mode for forced tool_choice the way the canonical opencode
    config does (see this branch's Responses-client fix for the other half
    of that same bug class)."""

    def _swapped_config(self) -> PipelineConfig:
        """A config already in the post-swap shape
        apply_external_user_provider_overrides() would have produced --
        this function's whole job is inverting exactly that shape."""
        return PipelineConfig(
            schema_name="cdif-discovery",
            default_provider="openrouter",
            providers=[
                ProviderConfig(
                    name="opencode", api_key_env="OPENCODE_API_KEY", default=False
                ),
                ProviderConfig(
                    name="openrouter", api_key_env="OPENROUTER_API_KEY", default=True
                ),
            ],
            agents=[
                AgentConfig(
                    id="a0",
                    name="A0",
                    fields=["schema_name"],
                    prompt="x",
                    provider="openrouter",
                    model="~deepseek/deepseek-v4-flash-latest",
                    extra_body={"reasoning": {"enabled": False}},
                ),
            ],
        )

    def test_restores_when_testing_provider_key_present(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "real-key")
        config = self._swapped_config()

        bootstrap.restore_testing_provider_if_key_available(config)

        assert config.agents[0].provider == "opencode"
        assert config.agents[0].model == "deepseek-v4-flash"
        assert config.agents[0].extra_body == {"thinking": {"type": "disabled"}}
        assert config.default_provider == "opencode"
        by_name = {p.name: p for p in config.providers}
        assert by_name["opencode"].default is True
        assert by_name["openrouter"].default is False

    def test_leaves_openrouter_swap_when_key_absent(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        config = self._swapped_config()

        bootstrap.restore_testing_provider_if_key_available(config)

        assert config.agents[0].provider == "openrouter"
        assert config.agents[0].model == "~deepseek/deepseek-v4-flash-latest"
        assert config.default_provider == "openrouter"

    def test_leaves_openrouter_swap_when_key_present_but_empty(self, monkeypatch):
        """An empty-string env var must not count as "available" -- same
        truthiness rule create_llm_client's own key resolution uses."""
        monkeypatch.setenv("OPENCODE_API_KEY", "")
        config = self._swapped_config()

        bootstrap.restore_testing_provider_if_key_available(config)

        assert config.agents[0].provider == "openrouter"

    def test_noop_when_config_never_declares_testing_provider(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "real-key")
        config = PipelineConfig(
            schema_name="cdif-discovery",
            default_provider="openai",
            providers=[ProviderConfig(name="openai", api_key_env="OPENAI_API_KEY")],
            agents=[
                AgentConfig(
                    id="a0", name="A0", fields=["schema_name"], prompt="x", provider="openai"
                ),
            ],
        )

        bootstrap.restore_testing_provider_if_key_available(config)  # must not raise

        assert config.agents[0].provider == "openai"

    def test_untouched_agent_on_a_third_provider_stays_untouched(self, monkeypatch):
        """Only agents actually sitting on the external-user default get
        restored -- an agent a user has already hand-set to some other
        provider entirely is not this function's business."""
        monkeypatch.setenv("OPENCODE_API_KEY", "real-key")
        config = self._swapped_config()
        config.providers.append(ProviderConfig(name="openai", api_key_env="OPENAI_API_KEY"))
        config.agents.append(
            AgentConfig(
                id="a1", name="A1", fields=["schema_name"], prompt="x", provider="openai"
            )
        )

        bootstrap.restore_testing_provider_if_key_available(config)

        assert config.agents[1].provider == "openai"

    def test_default_flags_untouched_when_nothing_was_restored(self, monkeypatch):
        """The provider.default/default_provider flip only happens
        alongside an actual restore -- a config that never went through the
        openrouter swap in the first place must come out exactly as it
        went in."""
        monkeypatch.setenv("OPENCODE_API_KEY", "real-key")
        config = PipelineConfig(
            schema_name="cdif-discovery",
            default_provider="openai",
            providers=[
                ProviderConfig(name="openai", api_key_env="OPENAI_API_KEY", default=True),
                ProviderConfig(name="opencode", api_key_env="OPENCODE_API_KEY", default=False),
            ],
            agents=[
                AgentConfig(
                    id="a0", name="A0", fields=["schema_name"], prompt="x", provider="openai"
                ),
            ],
        )

        bootstrap.restore_testing_provider_if_key_available(config)

        assert config.default_provider == "openai"
        by_name = {p.name: p for p in config.providers}
        assert by_name["openai"].default is True
        assert by_name["opencode"].default is False


class TestLoadPipelineConfig:
    def test_returns_config_and_schema_on_success(self, monkeypatch, tmp_path):
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(
            """
schema_name: cdif-discovery
agents:
  - id: a
    name: A
    fields: [schema_name]
    prompt: x
    provider: p
providers:
  - name: p
    base_url: http://localhost
    api_key_env: SOME_KEY
default_provider: p
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(bootstrap, "find_config", lambda: config_path)

        config, schema, error = bootstrap.load_pipeline_config()

        assert error is None
        assert config is not None
        assert schema is not None
        assert schema.name == "cdif-discovery"

    def test_applies_external_user_provider_overrides_even_when_found_directly(
        self, monkeypatch, tmp_path
    ):
        """The override must apply regardless of how config_path was
        resolved -- a dev running visor from an editable repo checkout
        hits find_config() and gets config/agents.yaml directly (not the
        frozen-seed path), and still gets openrouter as visor's default;
        only the file on disk stays opencode."""
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "schema_name": "cdif-discovery",
                    "providers": [
                        {"name": "opencode", "api_key_env": "OPENCODE_API_KEY", "default": True},
                        {"name": "openrouter", "api_key_env": "OPENROUTER_API_KEY", "default": False},
                    ],
                    "default_provider": "opencode",
                    "agents": [
                        {
                            "id": "a0",
                            "name": "A",
                            "fields": ["schema_name"],
                            "prompt": "x",
                            "provider": "opencode",
                            "model": "deepseek-v4-flash",
                            "extra_body": {"thinking": {"type": "disabled"}},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(bootstrap, "find_config", lambda: config_path)

        config, schema, error = bootstrap.load_pipeline_config()

        assert error is None
        assert config is not None
        assert config.default_provider == "openrouter"
        assert config.agents[0].provider == "openrouter"
        assert config.agents[0].model == "~deepseek/deepseek-v4-flash-latest"
        assert config.agents[0].extra_body == {"reasoning": {"enabled": False}}
        # The file on disk is untouched -- only load_pipeline_config()'s
        # in-memory result differs.
        on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert on_disk["default_provider"] == "opencode"
        assert on_disk["agents"][0]["provider"] == "opencode"

    def test_returns_error_message_on_any_failure_not_a_crash(self, monkeypatch):
        def _raise():
            raise FileNotFoundError("no configuration file found. Searched:\n  nowhere")

        monkeypatch.setattr(bootstrap, "find_config", _raise)
        monkeypatch.setattr(bootstrap, "bundled_config_path", lambda: None)

        config, schema, error = bootstrap.load_pipeline_config()

        assert config is None
        assert schema is None
        assert error is not None
        assert "no configuration file found" in error


class TestDataverseExportBundledPath:
    def test_none_when_not_frozen(self, monkeypatch):
        monkeypatch.delattr("sys.frozen", raising=False)
        assert bootstrap.dataverse_export_bundled_path() is None

    def test_returns_path_when_frozen_and_file_exists(self, monkeypatch, tmp_path):
        bundled_dir = tmp_path / "visor_default_config"
        bundled_dir.mkdir()
        (bundled_dir / "dataverse_export.yaml").write_text("enabled: true", encoding="utf-8")

        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

        result = bootstrap.dataverse_export_bundled_path()
        assert result == bundled_dir / "dataverse_export.yaml"


class TestResolveDataverseExportConfigPath:
    def test_prefers_repo_relative_path_when_present(self, monkeypatch, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "dataverse_export.yaml").write_text("enabled: true", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = bootstrap.resolve_dataverse_export_config_path()
        assert result == bootstrap.DATAVERSE_EXPORT_REPO_PATH

    def test_falls_back_to_bundled_when_repo_path_missing(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # no ./config/dataverse_export.yaml here
        bundled = tmp_path / "bundled_dataverse_export.yaml"
        bundled.write_text("enabled: true", encoding="utf-8")
        monkeypatch.setattr(bootstrap, "dataverse_export_bundled_path", lambda: bundled)

        result = bootstrap.resolve_dataverse_export_config_path()
        assert result == bundled

    def test_raises_when_neither_found(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "dataverse_export_bundled_path", lambda: None)

        with pytest.raises(FileNotFoundError):
            bootstrap.resolve_dataverse_export_config_path()


class TestLoadDataverseExportConfigSafe:
    def test_returns_config_on_success(self, monkeypatch, tmp_path):
        config_path = tmp_path / "dataverse_export.yaml"
        config_path.write_text(
            """
enabled: true
agent:
  id: dataverse_subject_classifier
  name: Classifier
  fields: [subject]
  prompt: x
  provider: p
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(bootstrap, "resolve_dataverse_export_config_path", lambda: config_path)

        config, error = bootstrap.load_dataverse_export_config_safe()

        assert error is None
        assert config is not None
        assert config.enabled is True
        assert config.agent.id == "dataverse_subject_classifier"

    def test_returns_error_message_on_any_failure_not_a_crash(self, monkeypatch):
        def _raise():
            raise FileNotFoundError("not found anywhere")

        monkeypatch.setattr(bootstrap, "resolve_dataverse_export_config_path", _raise)

        config, error = bootstrap.load_dataverse_export_config_safe()

        assert config is None
        assert error is not None
        assert "not found anywhere" in error
