"""Tests for visor.glue — form/paste/upload text -> temp file -> Pipeline."""

from __future__ import annotations

import json
import os

import pytest

from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from visor.glue import run_single, write_temp_input_from_dict, write_temp_input_from_text


class FakeLLMClient:
    def __init__(self, response_data: dict | None = None) -> None:
        self._response_data = response_data or {}

    @property
    def model(self) -> str:
        return "mock-model"

    def complete(self, prompt, response_model, system_prompt=None, **kw):  # noqa: ANN001, ANN201
        return response_model(**self._response_data)

    def complete_raw(self, prompt, system_prompt=None, **kw):  # noqa: ANN001, ANN201
        return "mock raw response"


def make_config() -> PipelineConfig:
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
            )
        ],
        providers=[ProviderConfig(name="mock", base_url="http://localhost", api_key_env="MOCK_KEY")],
        default_provider="mock",
    )


@pytest.fixture(autouse=True)
def _mock_api_key() -> None:
    os.environ["MOCK_KEY"] = "test-key"


class TestWriteTempInput:
    def test_from_text_is_read_unchanged_by_filesystem_input_source(self):
        text = json.dumps({"url": "https://x", "title": "T", "description": "D"})
        path = write_temp_input_from_text(text)
        try:
            resource = FilesystemInputSource().fetch(str(path))
            assert resource.url == "https://x"
            assert resource.title == "T"
        finally:
            path.unlink(missing_ok=True)

    def test_from_dict_roundtrips_through_filesystem_input_source(self):
        path = write_temp_input_from_dict(
            {"url": "https://y", "title": "Y", "description": "desc", "publisher": "Pub"}
        )
        try:
            resource = FilesystemInputSource().fetch(str(path))
            assert resource.url == "https://y"
            # publisher isn't a fixed ResourceDescription field — must survive
            # as an extra field, matching extra="allow" on ResourceDescription.
            assert resource.publisher == "Pub"
        finally:
            path.unlink(missing_ok=True)

    def test_invalid_json_text_raises_on_fetch_not_on_write(self):
        path = write_temp_input_from_text("not valid json{{{")
        try:
            with pytest.raises(ValueError):
                FilesystemInputSource().fetch(str(path))
        finally:
            path.unlink(missing_ok=True)


class TestRunSingle:
    def test_runs_pipeline_and_returns_result(self):
        path = write_temp_input_from_dict(
            {"url": "https://example.com/x", "title": "T", "description": "D"}
        )
        factory = lambda provider, **kw: FakeLLMClient({"titles": [{"name": "T", "title_type": "MainTitle"}]})  # noqa: E731
        try:
            result = run_single(make_config(), path, llm_factory=factory)
        finally:
            path.unlink(missing_ok=True)
        assert result.success is True
        assert result.document.get_field("titles") is not None

    def test_missing_file_raises_clearly(self, tmp_path):
        """Visor always writes the temp file itself right before calling
        run_single, so a missing path here means a real bug in the caller,
        not a normal failure mode — FilesystemInputSource.list_sources()
        returns [] for a nonexistent single-file pattern (no result at all,
        unlike a real fetch failure), so this must not be misread as a
        successful empty run."""
        missing = tmp_path / "does-not-exist.json"
        factory = lambda provider, **kw: FakeLLMClient()  # noqa: E731
        with pytest.raises(RuntimeError, match="no result"):
            run_single(make_config(), missing, llm_factory=factory)
