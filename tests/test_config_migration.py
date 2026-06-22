"""Tests for config migration (metadata_enricher.config.migrate).

migrate_json_to_yaml: converts legacy JSON (andrea_v3 format) to current
YAML PipelineConfig format.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import yaml

from metadata_enricher.config.models import PipelineConfig
from metadata_enricher.config.migrate import migrate_json_to_yaml


@pytest.fixture
def andrea_v3_dict() -> dict:
    """Return a minimal legacy andrea_v3.json structure (5 agents)."""
    return {
        "agents": [
            {
                "id": "core_metadata",
                "name": "Core Metadata Extractor",
                "description": "Extrae la metadata básica del recurso.",
                "output_fields": ["resource", "titles", "descriptions", "languages", "dates"],
                "prompt_template": "Eres un agente experto en extracción de metadata.",
                "depends_on": [],
                "use_chain_of_thought": True,
                "llm_config": {
                    "model": "deepseek-v4-flash",
                    "provider": "opencode",
                    "temperature": 0.2,
                    "max_tokens": None,
                },
            },
            {
                "id": "creators_publishers",
                "name": "Creators and Publishers",
                "description": "Extrae creadores y editores.",
                "output_fields": ["creators", "publishers"],
                "prompt_template": "Eres un agente experto en identificación de creadores.",
                "depends_on": ["core_metadata"],
                "use_chain_of_thought": True,
                "llm_config": {
                    "model": "deepseek-v4-flash",
                    "provider": "opencode",
                    "temperature": 0.0,
                    "max_tokens": None,
                },
            },
            {
                "id": "classification",
                "name": "Classification Agent",
                "description": "Clasifica el recurso.",
                "output_fields": ["categories", "subjects", "audiences"],
                "prompt_template": "Eres un agente experto en clasificación.",
                "depends_on": ["creators_publishers"],
                "use_chain_of_thought": True,
                "llm_config": {
                    "model": "deepseek-v4-flash",
                    "provider": "opencode",
                    "temperature": 0.0,
                    "max_tokens": None,
                },
            },
            {
                "id": "rights_funding_citations",
                "name": "Rights, Funding & Citations",
                "description": "Analiza licencia, financiamiento y citas.",
                "output_fields": ["rights", "funding_references", "citations"],
                "prompt_template": "Eres un agente especializado en licencias.",
                "depends_on": ["classification"],
                "use_chain_of_thought": True,
                "llm_config": {
                    "model": "deepseek-v4-flash",
                    "provider": "opencode",
                    "temperature": 0.0,
                    "max_tokens": None,
                },
            },
            {
                "id": "media_files",
                "name": "Media Files",
                "description": "Describe archivos multimedia.",
                "output_fields": ["media_files"],
                "prompt_template": "Eres un agente especializado en archivos multimedia.",
                "depends_on": ["rights_funding_citations"],
                "use_chain_of_thought": True,
                "llm_config": {
                    "model": "deepseek-v4-flash",
                    "provider": "opencode",
                    "temperature": 0.2,
                    "max_tokens": None,
                },
            },
        ],
    }


@pytest.fixture
def providers_dict() -> dict:
    """Return a sample providers.json structure."""
    return {
        "providers": {
            "opencode": {
                "api_base": "https://opencode.ai/zen/go/v1",
                "api_key_env": "OPENCODE_API_KEY",
            },
            "zai-coding-plan": {
                "api_base": "https://api.z.ai/api/coding/paas/v4",
                "api_key_env": "ZAI_API_KEY",
            },
        },
    }


class TestMigrateJsonToYaml:
    """migrate_json_to_yaml: legacy JSON → YAML PipelineConfig."""

    def _write_json(self, path: Path, data: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def test_converts_basic_structure(
        self,
        tmp_path: Path,
        andrea_v3_dict: dict,
        providers_dict: dict,
    ):
        """Happy path: converts 5 agents, renames fields, extracts llm_config."""
        json_path = self._write_json(tmp_path / "andrea_v3.json", andrea_v3_dict)
        self._write_json(tmp_path / "providers.json", providers_dict)

        yaml_path = migrate_json_to_yaml(json_path)

        assert yaml_path.exists()
        assert yaml_path.suffix == ".yaml"
        assert yaml_path.parent == json_path.parent

        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data["schema_name"] == "datacite-4.6"
        assert len(data["agents"]) == 5

        a0 = data["agents"][0]
        assert a0["id"] == "core_metadata"
        assert "output_fields" not in a0
        assert "prompt_template" not in a0
        assert "llm_config" not in a0
        assert a0["fields"] == ["resource", "titles", "descriptions", "languages", "dates"]
        assert a0["prompt"] == "Eres un agente experto en extracción de metadata."
        assert a0["model"] == "deepseek-v4-flash"
        assert a0["provider"] == "opencode"
        assert a0["temperature"] == 0.2
        assert a0["max_tokens"] is None
        assert a0["depends_on"] == []
        assert a0["use_chain_of_thought"] is True

        a4 = data["agents"][4]
        assert a4["id"] == "media_files"
        assert a4["depends_on"] == ["rights_funding_citations"]

        assert len(data["providers"]) == 2
        prov_names = {p["name"] for p in data["providers"]}
        assert prov_names == {"opencode", "zai-coding-plan"}

        opencode_prov = next(p for p in data["providers"] if p["name"] == "opencode")
        assert opencode_prov["base_url"] == "https://opencode.ai/zen/go/v1"
        assert opencode_prov["api_key_env"] == "OPENCODE_API_KEY"

    def test_produces_valid_pipeline_config(
        self,
        tmp_path: Path,
        andrea_v3_dict: dict,
        providers_dict: dict,
    ):
        """Migrated YAML validates as a PipelineConfig."""
        json_path = self._write_json(tmp_path / "andrea_v3.json", andrea_v3_dict)
        self._write_json(tmp_path / "providers.json", providers_dict)

        yaml_path = migrate_json_to_yaml(json_path)

        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        cfg = PipelineConfig.model_validate(data)
        assert len(cfg.agents) == 5
        assert cfg.schema_name == "datacite-4.6"
        assert cfg.default_provider == "opencode"

    def test_default_provider_set(self, tmp_path: Path, andrea_v3_dict: dict, providers_dict: dict):
        """default_provider is set to the first provider referenced by agents."""
        json_path = self._write_json(tmp_path / "andrea_v3.json", andrea_v3_dict)
        self._write_json(tmp_path / "providers.json", providers_dict)

        yaml_path = migrate_json_to_yaml(json_path)
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data["default_provider"] == "opencode"

    def test_multiple_providers_default_first_alphabetical(
        self,
        tmp_path: Path,
        providers_dict: dict,
    ):
        """When agents reference multiple providers, default is first alphabetically."""
        agents = {
            "agents": [
                {
                    "id": "a1",
                    "name": "Agent 1",
                    "output_fields": ["f1"],
                    "prompt_template": "Prompt",
                    "depends_on": [],
                    "use_chain_of_thought": False,
                    "llm_config": {
                        "model": "m1",
                        "provider": "zai-coding-plan",
                        "temperature": 0.0,
                    },
                },
                {
                    "id": "a2",
                    "name": "Agent 2",
                    "output_fields": ["f2"],
                    "prompt_template": "Prompt",
                    "depends_on": [],
                    "use_chain_of_thought": False,
                    "llm_config": {"model": "m2", "provider": "anthropic", "temperature": 0.0},
                },
            ],
        }
        json_path = self._write_json(tmp_path / "multi_provider.json", agents)
        self._write_json(tmp_path / "providers.json", providers_dict)

        yaml_path = migrate_json_to_yaml(json_path)
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data["default_provider"] == "anthropic"

    def test_no_providers_file(self, tmp_path: Path, andrea_v3_dict: dict):
        """Migration succeeds even without a sibling providers.json."""
        json_path = self._write_json(tmp_path / "andrea_v3.json", andrea_v3_dict)

        yaml_path = migrate_json_to_yaml(json_path)
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data["providers"] == []
        assert data["agents"][0]["provider"] == "opencode"

    def test_original_json_not_modified(self, tmp_path: Path, andrea_v3_dict: dict):
        """The original JSON file is never touched."""
        json_path = self._write_json(tmp_path / "andrea_v3.json", andrea_v3_dict)
        original_content = json_path.read_text(encoding="utf-8")

        migrate_json_to_yaml(json_path)

        assert json_path.read_text(encoding="utf-8") == original_content

    def test_logs_warning_for_unknown_fields(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Unknown fields in agent dict produce WARNING log messages."""
        agents = {
            "agents": [
                {
                    "id": "a1",
                    "name": "Agent 1",
                    "output_fields": ["f1"],
                    "prompt_template": "Prompt",
                    "llm_config": {"model": "m1", "provider": "p1", "temperature": 0.0},
                    "depends_on": [],
                    "use_chain_of_thought": False,
                    "unknown_field_xyz": "should warn",
                    "another_bad_field": 42,
                },
            ],
        }
        json_path = self._write_json(tmp_path / "with_unknown.json", agents)

        with caplog.at_level(logging.WARNING):
            migrate_json_to_yaml(json_path)

        warning_messages = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
        assert any("unknown_field_xyz" in m for m in warning_messages), warning_messages
        assert any("another_bad_field" in m for m in warning_messages), warning_messages

    def test_yaml_allow_unicode(self, tmp_path: Path):
        """Non-ASCII characters in prompts are preserved in YAML output."""
        agents = {
            "agents": [
                {
                    "id": "a1",
                    "name": "Agente de Prueba",
                    "output_fields": ["títulos"],
                    "prompt_template": "Eres un agente experto en extracción de metadatos. © 2024",
                    "llm_config": {"model": "m1", "provider": "p1", "temperature": 0.0},
                    "depends_on": [],
                    "use_chain_of_thought": False,
                },
            ],
        }
        json_path = self._write_json(tmp_path / "unicode_test.json", agents)

        yaml_path = migrate_json_to_yaml(json_path)
        content = yaml_path.read_text(encoding="utf-8")

        assert "©" in content
        assert "metadatos" in content
        assert "Agente de Prueba" in content
