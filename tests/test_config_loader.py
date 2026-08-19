"""Tests for config loader (metadata_enricher.config.loader).

load_config: YAML reading, env-var expansion, PipelineConfig validation.
find_config: file-discovery search-order logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from metadata_enricher.config.loader import find_config, load_config
from metadata_enricher.config.models import PipelineConfig

# ──────────────────────────────────────────────
# load_config
# ──────────────────────────────────────────────


class TestLoadConfig:
    """load_config: read YAML, expand env vars, validate as PipelineConfig."""

    def _write_yaml(self, path: Path, data: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        return path

    # -- happy path -----------------------------------------------

    def test_valid_minimal(self, tmp_path: Path):
        """A minimal valid YAML with 1 agent + 1 provider."""
        data = {
            "schema_name": "datacite-4.6",
            "agents": [
                {
                    "id": "explorer",
                    "name": "Explorer",
                    "fields": ["resource"],
                    "prompt": "Extract metadata.",
                    "provider": "opencode",
                },
            ],
            "providers": [
                {"name": "opencode", "api_key_env": "OPENCODE_API_KEY"},
            ],
        }
        p = self._write_yaml(tmp_path / "agents.yaml", data)
        cfg = load_config(p)
        assert isinstance(cfg, PipelineConfig)
        assert cfg.schema_name == "datacite-4.6"
        assert len(cfg.agents) == 1
        assert cfg.agents[0].id == "explorer"
        assert len(cfg.providers) == 1

    def test_full_config(self, tmp_path: Path):
        """A more realistic multi-agent config."""
        data = {
            "schema_name": "datacite-4.6",
            "agents": [
                {
                    "id": "core_metadata",
                    "name": "Core Metadata",
                    "fields": ["resource", "titles"],
                    "prompt": "Extract core metadata.",
                    "provider": "opencode",
                    "model": "deepseek-v4-flash",
                    "temperature": 0.2,
                    "use_chain_of_thought": True,
                },
                {
                    "id": "creators_publishers",
                    "name": "Creators and Publishers",
                    "fields": ["creators"],
                    "prompt": "Identify creators.",
                    "provider": "zai-coding-plan",
                    "depends_on": ["core_metadata"],
                },
            ],
            "providers": [
                {"name": "opencode", "api_key_env": "OPENCODE_API_KEY", "default": True},
                {
                    "name": "zai-coding-plan",
                    "base_url": "https://api.z.ai/api/coding/paas/v4",
                    "api_key_env": "ZAI_API_KEY",
                },
            ],
            "default_provider": "opencode",
            "strategies": {"context": "accumulative"},
        }
        p = self._write_yaml(tmp_path / "agents.yaml", data)
        cfg = load_config(p)
        assert len(cfg.agents) == 2
        assert cfg.default_provider == "opencode"
        assert cfg.strategies == {"context": "accumulative"}

    # -- error paths ----------------------------------------------

    def test_missing_file(self, tmp_path: Path):
        """load_config raises FileNotFoundError for non-existent path."""
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(FileNotFoundError, match="not found"):
            load_config(missing)

    def test_empty_yaml(self, tmp_path: Path):
        """Empty YAML file raises ValueError."""
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_config(p)

    def test_invalid_yaml(self, tmp_path: Path):
        """Malformed YAML raises YAMLError."""
        p = tmp_path / "bad.yaml"
        p.write_text("{unclosed: [", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_config(p)

    def test_validation_error(self, tmp_path: Path):
        """Valid YAML but missing required PipelineConfig fields raises ValidationError."""
        data = {"agents": []}  # missing schema_name, empty agents list
        p = self._write_yaml(tmp_path / "bad_schema.yaml", data)
        with pytest.raises(ValidationError):
            load_config(p)

    # -- env-var expansion ----------------------------------------

    def test_expands_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """${VAR} syntax is expanded via os.path.expandvars."""
        monkeypatch.setenv("MY_PROVIDER", "opencode")
        monkeypatch.setenv("MY_KEY_ENV", "OPENCODE_API_KEY")

        data = {
            "schema_name": "datacite-4.6",
            "agents": [
                {
                    "id": "explorer",
                    "name": "Explorer",
                    "fields": ["resource"],
                    "prompt": "Extract.",
                    "provider": "${MY_PROVIDER}",
                },
            ],
            "providers": [
                {"name": "${MY_PROVIDER}", "api_key_env": "${MY_KEY_ENV}"},
            ],
        }
        p = self._write_yaml(tmp_path / "agents.yaml", data)
        cfg = load_config(p)
        assert cfg.agents[0].provider == "opencode"
        assert cfg.providers[0].name == "opencode"
        assert cfg.providers[0].api_key_env == "OPENCODE_API_KEY"

    def test_unknown_env_var_left_as_is(self, tmp_path: Path):
        """An undefined ${VAR} is left unchanged by expandvars."""
        data = {
            "schema_name": "datacite-4.6",
            "agents": [
                {
                    "id": "a1",
                    "name": "Agent 1",
                    "fields": ["f1"],
                    "prompt": "Do stuff.",
                    "provider": "${UNDEFINED_VAR}",
                },
            ],
            "providers": [
                {"name": "${UNDEFINED_VAR}", "api_key_env": "SOME_KEY"},
            ],
        }
        p = self._write_yaml(tmp_path / "agents.yaml", data)
        cfg = load_config(p)
        # expandvars leaves undefined vars as-is, so validation would fail
        # because provider name must match a provider in the list.
        # But the loaded string would be literally "${UNDEFINED_VAR}".
        assert cfg.agents[0].provider == "${UNDEFINED_VAR}"


# ──────────────────────────────────────────────
# find_config
# ──────────────────────────────────────────────


class TestFindConfig:
    """find_config: search-order logic."""

    def test_explicit_path(self, tmp_path: Path):
        """Explicit path is returned when it exists."""
        cfg = tmp_path / "my_config.yaml"
        cfg.write_text("schema_name: datacite-4.6\nagents: []\nproviders: []\n", encoding="utf-8")
        found = find_config(explicit=cfg)
        assert found == cfg.resolve()

    def test_explicit_path_missing_skips(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When explicit path does not exist, continue searching."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "agents.yaml").write_text("x: 1\n", encoding="utf-8")
        found = find_config(explicit=tmp_path / "nonexistent.yaml")
        assert found == (tmp_path / "config" / "agents.yaml").resolve()

    def test_config_agents_yaml_in_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Finds ./config/agents.yaml when it exists."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        agents = tmp_path / "config" / "agents.yaml"
        agents.write_text(
            "schema_name: datacite-4.6\nagents: []\nproviders: []\n", encoding="utf-8"
        )
        found = find_config()
        assert found == agents.resolve()

    def test_user_config_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Finds ~/.config/gema/agents.yaml when it exists."""
        monkeypatch.chdir(tmp_path)  # no ./config/agents.yaml
        # Patch home dir to tmp_path so we can control ~/.config
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        user_cfg = tmp_path / ".config" / "gema" / "agents.yaml"
        user_cfg.parent.mkdir(parents=True)
        user_cfg.write_text(
            "schema_name: datacite-4.6\nagents: []\nproviders: []\n", encoding="utf-8"
        )
        found = find_config()
        assert found == user_cfg.resolve()

    def test_gema_config_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Finds the path from $GEMA_CONFIG env var."""
        monkeypatch.chdir(tmp_path)  # no ./config/agents.yaml
        monkeypatch.setattr(Path, "home", lambda: tmp_path)  # no ~/.config/...
        env_cfg = tmp_path / "from_env" / "agents.yaml"
        env_cfg.parent.mkdir(parents=True)
        env_cfg.write_text(
            "schema_name: datacite-4.6\nagents: []\nproviders: []\n", encoding="utf-8"
        )
        monkeypatch.setenv("GEMA_CONFIG", str(env_cfg))
        found = find_config()
        assert found == env_cfg.resolve()

    def test_precedence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Explicit path beats ./config/agents.yaml which beats env var."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Location 1: explicit
        explicit = tmp_path / "explicit.yaml"
        explicit.write_text("a: 1\n", encoding="utf-8")

        # Location 2: ./config/agents.yaml
        (tmp_path / "config").mkdir()
        cwd_cfg = tmp_path / "config" / "agents.yaml"
        cwd_cfg.write_text("b: 2\n", encoding="utf-8")

        # Location 4: $GEMA_CONFIG
        env_cfg = tmp_path / "env.yaml"
        env_cfg.write_text("d: 4\n", encoding="utf-8")
        monkeypatch.setenv("GEMA_CONFIG", str(env_cfg))

        found = find_config(explicit=explicit)
        assert found == explicit.resolve()

        found2 = find_config(explicit=None)
        assert found2 == cwd_cfg.resolve()

    def test_none_found_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When no config file exists anywhere, raise FileNotFoundError."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Ensure no files exist in any search location
        with pytest.raises(FileNotFoundError, match="no configuration file found"):
            find_config()
