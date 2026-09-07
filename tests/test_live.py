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

        name = result.document.get_field("schema:name")
        assert name, "schema:name field missing or empty"
        assert isinstance(name, str)


class TestLivePipelineStructural:
    """Verify pipeline output has the expected CDIF Discovery structure."""

    def test_output_has_multiple_field_groups(self) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(SAMPLE_INPUT))

        assert len(results) == 1
        assert results[0].success
        assert results[0].document is not None

        schema = get_registry().get("cdif-discovery")
        writer = OutputWriter(schema)
        json_str = writer.format_json(results[0].document)
        output: dict = json.loads(json_str)

        expected_groups = {"@id", "@type", "schema:name", "schema:description", "schema:creator"}
        actual_groups = set(output.keys())
        missing = expected_groups - actual_groups
        assert not missing, f"Missing expected field groups: {missing}"
        assert len(actual_groups) >= 8, (
            f"Expected >=8 field groups, got {len(actual_groups)}: {sorted(actual_groups)}"
        )

    def test_name_non_empty(self) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(SAMPLE_INPUT))

        assert len(results) == 1
        assert results[0].document is not None

        name = results[0].document.get_field("schema:name")
        assert isinstance(name, str)
        assert name.strip(), "schema:name is empty"

    def test_creators_have_names(self) -> None:
        source = FilesystemInputSource()
        pipeline = _build_pipeline()
        results = pipeline.run(source, pattern=str(SAMPLE_INPUT))

        assert len(results) == 1
        assert results[0].document is not None

        creators = results[0].document.get_field("schema:creator")
        assert creators is not None
        assert isinstance(creators, dict)
        creator_list = creators.get("@list")
        assert isinstance(creator_list, list)
        assert len(creator_list) > 0, "schema:creator @list is empty"
        for creator in creator_list:
            assert isinstance(creator, dict)
            assert creator.get("schema:name"), (
                f"creator missing schema:name: {list(creator.keys())}"
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

        json_str = OutputWriter(get_registry().get("cdif-discovery")).format_json(
            result.document
        )
        output: dict = json.loads(json_str)
        assert len(output) >= 5, (
            f"Output for {input_file.name} has only {len(output)} fields"
        )
