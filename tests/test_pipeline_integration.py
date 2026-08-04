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


class AlwaysFailingLLMClient:
    """Mock LLM client that always raises — simulates a bad API key / unreachable provider."""

    @property
    def model(self) -> str:
        return "mock-model"

    def complete(
        self, prompt: str, response_model: type, system_prompt: str | None = None, **kw: object
    ) -> object:
        raise RuntimeError("401 Unauthorized")

    def complete_raw(self, prompt: str, system_prompt: str | None = None, **kw: object) -> str:
        raise RuntimeError("401 Unauthorized")


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


def make_publisher_config() -> PipelineConfig:
    """Config whose one agent produces the 'publishers' field, for PID-validation tests."""
    return PipelineConfig(
        schema_name="datacite-4.6",
        agents=[
            AgentConfig(
                id="publishers-agent",
                name="Publishers Agent",
                fields=["publishers"],
                prompt="Extract publisher from {url} {title} {description}",
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

    def test_pipeline_all_agents_failing_is_not_reported_as_success(self, tmp_path):
        """Every agent erroring (bad key/unreachable provider) must be a failure,
        never a 'successful' empty document.
        """
        make_input_file(
            tmp_path,
            {
                "url": "https://example.com/resource",
                "title": "Test Dataset",
                "description": "A test dataset for integration testing",
            },
        )
        failing_factory = lambda provider, **kw: AlwaysFailingLLMClient()  # noqa: E731
        pipeline = Pipeline(config=make_test_config(), llm_factory=failing_factory)
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is False
        assert result.error is not None
        assert "401" in result.error

    @staticmethod
    def _make_mixed_success_failure_config() -> PipelineConfig:
        """PipelineConfig with 2 independent agents: one always succeeds
        (provider 'mock-ok'), the other always fails (provider 'mock-fail').
        """
        return PipelineConfig(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig(
                    id="titles-agent",
                    name="Titles Agent",
                    fields=["titles"],
                    prompt="Extract titles from {url} {title} {description}",
                    provider="mock-ok",
                    model="mock-model",
                ),
                AgentConfig(
                    id="descriptions-agent",
                    name="Descriptions Agent",
                    fields=["descriptions"],
                    prompt="Extract descriptions from {url} {title} {description}",
                    provider="mock-fail",
                    model="mock-model",
                ),
            ],
            providers=[
                ProviderConfig(name="mock-ok", base_url="http://localhost", api_key_env="MOCK_KEY"),
                ProviderConfig(
                    name="mock-fail", base_url="http://localhost", api_key_env="MOCK_KEY"
                ),
            ],
            default_provider="mock-ok",
        )

    @staticmethod
    def _mixed_factory(provider, **kw):  # noqa: ARG001, ANN001
        return FakeLLMClient() if provider.name == "mock-ok" else AlwaysFailingLLMClient()

    def test_pipeline_partial_agent_failure_is_a_failure_by_default(self, tmp_path):
        """One agent succeeds, another fails (e.g. rate-limited) -> by default
        this must be a failure, not a half-complete document written silently.
        """
        make_input_file(
            tmp_path,
            {
                "url": "https://example.com/resource",
                "title": "Test Dataset",
                "description": "A test dataset for integration testing",
            },
        )
        pipeline = Pipeline(
            config=self._make_mixed_success_failure_config(), llm_factory=self._mixed_factory
        )
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]

        assert result.success is False
        assert result.document is None
        assert result.error is not None
        assert "descriptions" in result.error
        assert "401" in result.error

    def test_pipeline_partial_agent_failure_allow_partial_reports_warnings(self, tmp_path):
        """Same mixed success/failure, but with allow_partial=True: best-effort
        document is written and the missing fields surface as warnings.
        """
        make_input_file(
            tmp_path,
            {
                "url": "https://example.com/resource",
                "title": "Test Dataset",
                "description": "A test dataset for integration testing",
            },
        )
        pipeline = Pipeline(
            config=self._make_mixed_success_failure_config(),
            llm_factory=self._mixed_factory,
            allow_partial=True,
        )
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]

        assert result.success is True
        assert result.document is not None
        assert result.document.get_field("titles") is not None
        assert len(result.warnings) == 1
        assert "descriptions" in result.warnings[0]
        assert "401" in result.warnings[0]


class TestPipelinePidValidation:
    """Pipeline: automatic PID validation runs on every resource by default."""

    def test_malformed_pid_surfaces_as_warning_by_default(self, tmp_path, llm_factory):
        """validate_pids defaults to True — a bad PID must not need an extra flag to be caught."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        config = make_publisher_config()
        config.validate_pids_live = False  # format check only — no network in a unit test
        factory = lambda provider, **kw: FakeLLMClient(  # noqa: E731
            {
                "fields": {
                    "publishers": [
                        {
                            "publisher_name": "Test Publisher",
                            "publisher_identifier": "https://ror.org/BADID",
                            "publisher_identifier_scheme": "ROR",
                        }
                    ]
                }
            }
        )
        results = Pipeline(config=config, llm_factory=factory).run(
            FilesystemInputSource(), pattern=str(tmp_path / "*.json")
        )
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert any("malformed ROR" in w for w in result.warnings)

    def test_well_formed_pid_produces_no_warning(self, tmp_path, llm_factory):
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        config = make_publisher_config()
        config.validate_pids_live = False
        factory = lambda provider, **kw: FakeLLMClient(  # noqa: E731
            {
                "fields": {
                    "publishers": [
                        {
                            "publisher_name": "Test Publisher",
                            "publisher_identifier": "https://ror.org/02sevrz47",
                            "publisher_identifier_scheme": "ROR",
                        }
                    ]
                }
            }
        )
        results = Pipeline(config=config, llm_factory=factory).run(
            FilesystemInputSource(), pattern=str(tmp_path / "*.json")
        )
        assert results[0].warnings == []

    def test_validate_pids_false_disables_check_entirely(self, tmp_path, llm_factory):
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        config = make_publisher_config()
        config.validate_pids = False
        factory = lambda provider, **kw: FakeLLMClient(  # noqa: E731
            {
                "fields": {
                    "publishers": [
                        {
                            "publisher_name": "Test Publisher",
                            "publisher_identifier": "https://ror.org/BADID",
                            "publisher_identifier_scheme": "ROR",
                        }
                    ]
                }
            }
        )
        results = Pipeline(config=config, llm_factory=factory).run(
            FilesystemInputSource(), pattern=str(tmp_path / "*.json")
        )
        assert results[0].warnings == []

    def test_pid_validation_exception_is_caught_not_propagated(self, tmp_path, llm_factory, monkeypatch):
        """validate_pids() is defensive by design and shouldn't raise, but if
        it somehow does (e.g. a future bug), that must not crash the whole
        resource — same contract as the enrichment step's own try/except."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("pid validator blew up")

        monkeypatch.setattr("metadata_enricher.enrichers.pid_validator.validate_pids", _boom)
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert result.error is None
        assert result.document.get_field("titles") is not None


class FakeEnricher:
    """Stand-in for IdentifierEnricher — marks the document, no network."""

    def __init__(self, raise_error: bool = False) -> None:
        self.raise_error = raise_error
        self.called_with = None

    def enrich(self, document):
        self.called_with = document
        if self.raise_error:
            raise RuntimeError("enrichment blew up")
        document.set_field("publishers", [{"publisher_name": "enriched-by-fake"}])
        return document


class TestPipelineIdentifierEnrichmentWiring:
    """Pipeline: identifier enrichment step actually runs, and failures don't crash the resource."""

    def test_injected_enricher_runs_and_mutates_document(self, tmp_path, llm_factory):
        """Explicit injection must run regardless of enable_identifier_enrichment,
        matching the llm_factory injection pattern — and its effect must land
        in the final document."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        fake = FakeEnricher()
        config = make_test_config()
        assert config.enable_identifier_enrichment is False
        pipeline = Pipeline(config=config, llm_factory=llm_factory, identifier_enricher=fake)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert fake.called_with is not None
        assert result.document.get_field("publishers") == [{"publisher_name": "enriched-by-fake"}]

    def test_enrichment_exception_is_caught_not_propagated(self, tmp_path, llm_factory):
        """An enrichment failure (e.g. ROR/ISNI/ORCID down) must not fail the
        whole resource — the pre-enrichment document is still returned as a
        success, same as the merger's output before enrichment ran."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        fake = FakeEnricher(raise_error=True)
        pipeline = Pipeline(
            config=make_test_config(), llm_factory=llm_factory, identifier_enricher=fake
        )
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert result.error is None
        assert fake.called_with is not None
        # The fake raises before mutating — document must be the merger's
        # unmodified output, not None and not crashed.
        assert result.document.get_field("titles") is not None
