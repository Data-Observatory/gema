"""Tests for live API end-to-end — requires ZAI_API_KEY, run with -m live."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from metadata_enricher.config.loader import load_config
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.llm.factory import reset_client_cache
from metadata_enricher.output import OutputWriter
from metadata_enricher.pipeline import Pipeline
from metadata_enricher.schemas import get_registry

CONFIG_PATH = Path("config/agents.yaml")
INPUTS_DIR = Path("tests/fixtures/golden/inputs")
SAMPLE_INPUT = INPUTS_DIR / "sample_input01.json"

_HAS_ZAI_KEY = bool(os.environ.get("ZAI_API_KEY"))
_SKIP_REASON = "Set ZAI_API_KEY in environment to run live tests"

pytestmark = [pytest.mark.live, pytest.mark.skipif(not _HAS_ZAI_KEY, reason=_SKIP_REASON)]


def _build_pipeline() -> Pipeline:
    reset_client_cache()
    config = load_config(CONFIG_PATH)
    return Pipeline(config=config)


class TestLiveSingleAgent:
    """Verify a single agent produces structured output via real API."""

    def test_core_metadata_agent_returns_data(self) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(SAMPLE_INPUT))

        assert len(results) == 1
        result = results[0]
        assert result.success, f"Pipeline failed: {result.error}"
        assert result.document is not None

        resource = result.document.get_field("resource")
        assert resource is not None, "resource field missing"
        assert isinstance(resource, dict)
        assert len(resource) > 0, "resource dict is empty"


class TestLivePipelineStructural:
    """Verify pipeline output has expected DataCite structure."""

    def test_output_has_multiple_field_groups(self) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(SAMPLE_INPUT))

        assert len(results) == 1
        assert results[0].success
        assert results[0].document is not None

        schema = get_registry().get("datacite-4.6")
        writer = OutputWriter(schema)
        json_str = writer.format_json(results[0].document)
        output: dict = json.loads(json_str)

        expected_groups = {"resource", "titles", "creators", "dates", "descriptions"}
        actual_groups = set(output.keys())
        missing = expected_groups - actual_groups
        assert not missing, f"Missing expected field groups: {missing}"
        assert len(actual_groups) >= 8, (
            f"Expected >=8 field groups, got {len(actual_groups)}: {sorted(actual_groups)}"
        )

    def test_titles_non_empty(self) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(SAMPLE_INPUT))

        assert len(results) == 1
        assert results[0].document is not None

        titles = results[0].document.get_field("titles")
        assert titles is not None
        assert isinstance(titles, list)
        assert len(titles) > 0, "titles list is empty"
        first = titles[0]
        assert isinstance(first, dict)
        assert "title" in first or "name" in first, (
            f"title/name key missing from first title entry: {list(first.keys())}"
        )

    def test_creators_have_name_identifiers(self) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(SAMPLE_INPUT))

        assert len(results) == 1
        assert results[0].document is not None

        creators = results[0].document.get_field("creators")
        assert creators is not None
        assert isinstance(creators, list)
        assert len(creators) > 0, "creators list is empty"
        for creator in creators:
            assert isinstance(creator, dict)
            assert "creator_name" in creator or "name" in creator, (
                f"creator missing name field: {list(creator.keys())}"
            )


class TestLiveMultipleInputs:
    """Verify pipeline handles all 3 sample inputs without errors."""

    @pytest.mark.parametrize("input_file", sorted(INPUTS_DIR.glob("*.json")))
    def test_all_inputs_succeed(self, input_file: Path) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(input_file))

        assert len(results) == 1
        result = results[0]
        assert result.success, f"Pipeline failed for {input_file.name}: {result.error}"
        assert result.document is not None

        json_str = OutputWriter(get_registry().get("datacite-4.6")).format_json(
            result.document
        )
        output: dict = json.loads(json_str)
        assert len(output) >= 5, (
            f"Output for {input_file.name} has only {len(output)} fields"
        )
