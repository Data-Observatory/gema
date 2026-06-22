"""Integration tests for the end-to-end Pipeline with mocked LLM."""

from __future__ import annotations

import json
import os

import pytest

from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.pipeline import Pipeline
from metadata_enricher.types import ResourceDescription


class FakeLLMClient:
    """Mock LLM client that returns predetermined responses."""

    def __init__(self, response_data: dict | None = None) -> None:
        self._response_data = response_data or {}

    @property
    def model(self) -> str:
        return "mock-model"

    def complete(
        self, prompt: str, response_model: type, system_prompt: str | None = None, **kw: object
    ) -> object:
        data = self._response_data.get("fields", {})
        return response_model(**data)

    def complete_raw(self, prompt: str, system_prompt: str | None = None, **kw: object) -> str:
        return "mock raw response"


def make_test_config() -> PipelineConfig:
    """Create minimal PipelineConfig for testing."""
    return PipelineConfig(
        schema_name="datacite-4.6",
        agents=[
            AgentConfig(
                id="titles-agent",
                name="Titles Agent",
                fields=["titles"],
                prompt="Extract titles from {url} {title} {description}",
                provider="mock",
                model="mock-model",
            ),
        ],
        providers=[
            ProviderConfig(name="mock", base_url="http://localhost", api_key_env="MOCK_KEY"),
        ],
        default_provider="mock",
    )


def make_input_file(tmp_path: pytest.TempPathFactory, data: dict) -> str:  # noqa: ARG001
    """Write a JSON input file into *tmp_path*."""
    f = tmp_path / "input.json"
    f.write_text(json.dumps(data))
    return str(f)


@pytest.fixture(autouse=True)
def _mock_api_key() -> None:
    """Ensure MOCK_KEY env var is set (needed by factory when llm_factory is None)."""
    os.environ["MOCK_KEY"] = "test-key"


@pytest.fixture
def llm_factory():
    """Return a factory that produces FakeLLMClient instances."""
    return lambda provider, **kw: FakeLLMClient()


class TestPipelineIntegration:
    """Pipeline integration tests with mocked LLM."""

    def test_pipeline_empty_input(self, tmp_path, llm_factory):
        """No files matching pattern -> empty results list."""
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.nonexistent"))
        assert len(results) == 0

    def test_pipeline_processes_resource(self, tmp_path, llm_factory):
        """One valid input -> PipelineResult.success=True, document has 'titles' field."""
        make_input_file(
            tmp_path,
            {
                "url": "https://example.com/resource",
                "title": "Test Dataset",
                "description": "A test dataset for integration testing",
            },
        )
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert result.error is None
        assert result.document is not None
        assert result.document.get_field("titles") is not None

    def test_pipeline_invalid_resource(self, tmp_path, llm_factory):
        """Input with no url/title/description -> validation fails."""
        make_input_file(tmp_path, {"doi": "10.1234/test"})
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is False
        assert result.error is not None
        assert "Validation failed" in result.error

    def test_pipeline_error_isolation(self, tmp_path, llm_factory):
        """2 inputs, one valid one invalid -> 2 results, 1 success 1 failure."""
        valid_file = tmp_path / "valid.json"
        valid_file.write_text(
            json.dumps(
                {
                    "url": "https://example.com/valid",
                    "title": "Valid Resource",
                    "description": "A valid resource",
                }
            )
        )
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text(json.dumps({"some_field": "no content"}))

        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.json"))
        assert len(results) == 2

        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0].error is not None
        assert "Validation failed" in failures[0].error

    def test_pipeline_result_properties(self, tmp_path, llm_factory):
        """Verify PipelineResult.success / document / error / resource fields."""
        make_input_file(
            tmp_path,
            {
                "url": "https://example.com/res",
                "title": "Test",
                "description": "Desc",
            },
        )
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]

        assert isinstance(result.resource, ResourceDescription)
        assert result.resource.url == "https://example.com/res"
        assert result.document is not None
        assert result.error is None
        assert result.success is True
