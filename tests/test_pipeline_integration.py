"""Integration tests for the end-to-end Pipeline with mocked LLM."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.pipeline import Pipeline, _aggregate_token_usage
from metadata_enricher.types import AgentResult, ResourceDescription, TokenUsage


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


class FailingInputSource:
    """InputSource whose fetch() always raises — simulates a bad path/permissions/IO error."""

    def __init__(self, sources: list[str]) -> None:
        self._sources = sources

    def fetch(self, source: str) -> ResourceDescription:
        raise OSError("disk on fire")

    def list_sources(self, pattern: str) -> list[str]:  # noqa: ARG002
        return self._sources


class TestPipelineDefensiveExceptBranches:
    """Each pipeline stage isolates its own exceptions into a failed
    PipelineResult rather than propagating and aborting the whole batch."""

    def test_fetch_failure_is_isolated_as_a_result(self, llm_factory):
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        source = FailingInputSource(["bad-source.json"])
        results = pipeline.run(source, pattern="*.json")
        assert len(results) == 1
        result = results[0]
        assert result.success is False
        assert result.error is not None
        assert "Fetch failed" in result.error
        assert "disk on fire" in result.error
        assert result.source_path == "bad-source.json"

    def test_registry_build_failure_is_isolated_as_a_result(
        self, tmp_path, llm_factory, monkeypatch
    ):
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )

        def _boom(*args, **kwargs):
            raise ValueError("bad agent config")

        monkeypatch.setattr("metadata_enricher.pipeline.AgentRegistry", _boom)
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is False
        assert result.error is not None
        assert "Registry build failed" in result.error
        assert "bad agent config" in result.error

    def test_orchestrator_failure_is_isolated_as_a_result(
        self, tmp_path, llm_factory, monkeypatch
    ):
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("cycle detected")

        monkeypatch.setattr("metadata_enricher.pipeline.Orchestrator", _boom)
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is False
        assert result.error is not None
        assert "Orchestration failed" in result.error
        assert "cycle detected" in result.error

    def test_merge_failure_is_isolated_as_a_result(self, tmp_path, llm_factory, monkeypatch):
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )

        def _boom(*args, **kwargs):
            raise ValueError("schema mismatch")

        monkeypatch.setattr("metadata_enricher.pipeline.MetadataMerger", _boom)
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is False
        assert result.error is not None
        assert "Merge failed" in result.error
        assert "schema mismatch" in result.error


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


class FakeDOIResolver:
    """Stand-in for DOIResolverEnricher — marks the document, no network."""

    def __init__(self, raise_error: bool = False) -> None:
        self.raise_error = raise_error
        self.called_with = None

    def enrich(self, document):
        self.called_with = document
        if self.raise_error:
            raise RuntimeError("doi resolution blew up")
        document.set_field("publishers", [{"publisher_name": "backfilled-by-fake"}])
        return document


class TestPipelineDOIResolutionWiring:
    """Pipeline: DOI resolution step actually runs, and failures don't crash the resource."""

    def test_injected_resolver_runs_and_mutates_document(self, tmp_path, llm_factory):
        """Explicit injection must run regardless of enable_doi_resolution,
        matching the identifier_enricher injection pattern — and its effect
        must land in the final document."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        fake = FakeDOIResolver()
        config = make_test_config()
        assert config.enable_doi_resolution is False
        pipeline = Pipeline(config=config, llm_factory=llm_factory, doi_resolver=fake)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert fake.called_with is not None
        assert result.document.get_field("publishers") == [{"publisher_name": "backfilled-by-fake"}]

    def test_resolution_exception_is_caught_not_propagated(self, tmp_path, llm_factory):
        """A Crossref lookup failure must not fail the whole resource — the
        pre-resolution document is still returned as a success."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        fake = FakeDOIResolver(raise_error=True)
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory, doi_resolver=fake)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert result.error is None
        assert fake.called_with is not None
        assert result.document.get_field("titles") is not None

    def test_runs_before_identifier_enrichment(self, tmp_path, llm_factory):
        """DOI resolution must run BEFORE identifier enrichment — a
        publisher it backfills should still be visible to (and thus
        resolvable by) the identifier enricher that runs right after."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        call_order: list[str] = []

        class OrderTrackingDOIResolver:
            def enrich(self, document):
                call_order.append("doi_resolver")
                return document

        class OrderTrackingIdentifierEnricher:
            def enrich(self, document):
                call_order.append("identifier_enricher")
                return document

        pipeline = Pipeline(
            config=make_test_config(),
            llm_factory=llm_factory,
            doi_resolver=OrderTrackingDOIResolver(),
            identifier_enricher=OrderTrackingIdentifierEnricher(),
        )
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert results[0].success is True
        assert call_order == ["doi_resolver", "identifier_enricher"]


class PromptCapturingLLMClient(FakeLLMClient):
    """FakeLLMClient that records every prompt it was called with, so tests
    can verify what the agent actually saw (e.g. whether fetched_content
    made it into the formatted prompt)."""

    def __init__(self, response_data: dict | None = None) -> None:
        super().__init__(response_data)
        self.prompts: list[str] = []

    def complete(
        self, prompt: str, response_model: type, system_prompt: str | None = None, **kw: object
    ) -> object:
        self.prompts.append(prompt)
        return super().complete(prompt, response_model, system_prompt, **kw)


class TestPipelineContentFetchWiring:
    """Pipeline: opt-in auto-fetch of resource.url into fetched_content,
    wired to run once per resource before agent orchestration."""

    def test_disabled_by_default_never_fetches(self, tmp_path, llm_factory) -> None:
        """enable_content_fetch defaults to False -> zero behavior change
        from today, fetch_page_content is never even called."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/resource", "title": "T", "description": "D"},
        )
        config = make_test_config()
        assert config.enable_content_fetch is False
        with patch(
            "metadata_enricher.enrichers.content_fetcher.fetch_page_content"
        ) as mock_fetch:
            pipeline = Pipeline(config=config, llm_factory=llm_factory)
            results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        mock_fetch.assert_not_called()
        assert len(results) == 1
        assert results[0].resource.fetched_content is None

    def test_enabled_with_empty_content_and_url_fetches_and_flows_to_agent(
        self, tmp_path
    ) -> None:
        """enable_content_fetch=True + empty fetched_content + a url ->
        fetch_page_content is called, and its result ends up both on the
        resource and in the text the agent's prompt was built from."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/resource", "title": "T", "description": "D"},
        )
        config = make_test_config()
        config.enable_content_fetch = True

        capturing_client = PromptCapturingLLMClient()
        factory = lambda provider, **kw: capturing_client  # noqa: E731

        with patch(
            "metadata_enricher.enrichers.content_fetcher.fetch_page_content",
            return_value="Fetched page body text",
        ) as mock_fetch:
            pipeline = Pipeline(config=config, llm_factory=factory)
            results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))

        mock_fetch.assert_called_once_with("https://example.com/resource")
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].resource.fetched_content == "Fetched page body text"
        assert any("Fetched page body text" in p for p in capturing_client.prompts)

    def test_enabled_but_content_already_present_does_not_fetch(
        self, tmp_path, llm_factory
    ) -> None:
        """Caller-supplied fetched_content is never overwritten — fetch_page_content
        must not even be called when content is already there."""
        make_input_file(
            tmp_path,
            {
                "url": "https://example.com/resource",
                "title": "T",
                "description": "D",
                "fetched_content": "Caller-supplied content",
            },
        )
        config = make_test_config()
        config.enable_content_fetch = True
        with patch(
            "metadata_enricher.enrichers.content_fetcher.fetch_page_content"
        ) as mock_fetch:
            pipeline = Pipeline(config=config, llm_factory=llm_factory)
            results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        mock_fetch.assert_not_called()
        assert len(results) == 1
        assert results[0].resource.fetched_content == "Caller-supplied content"

    def test_enabled_but_no_url_does_not_fetch(self, tmp_path, llm_factory) -> None:
        """No url on the resource -> nothing to fetch, no call at all."""
        make_input_file(tmp_path, {"title": "T", "description": "D"})
        config = make_test_config()
        config.enable_content_fetch = True
        with patch(
            "metadata_enricher.enrichers.content_fetcher.fetch_page_content"
        ) as mock_fetch:
            pipeline = Pipeline(config=config, llm_factory=llm_factory)
            pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        mock_fetch.assert_not_called()

    def test_fetch_failure_returning_none_is_tolerated(self, tmp_path, llm_factory) -> None:
        """fetch_page_content returning None (its documented failure contract)
        must not fail the resource — processing continues with no fetched_content,
        same as if the feature were off."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/resource", "title": "T", "description": "D"},
        )
        config = make_test_config()
        config.enable_content_fetch = True
        with patch(
            "metadata_enricher.enrichers.content_fetcher.fetch_page_content",
            return_value=None,
        ):
            pipeline = Pipeline(config=config, llm_factory=llm_factory)
            results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].resource.fetched_content is None

    def test_unexpected_exception_from_fetcher_is_isolated_not_fatal(
        self, tmp_path, llm_factory
    ) -> None:
        """Defense in depth: even if fetch_page_content somehow raised (it
        shouldn't, by contract), the resource must still process successfully
        with no fetched_content, matching the "one resource's failure never
        blocks the batch" invariant."""
        make_input_file(
            tmp_path,
            {"url": "https://example.com/resource", "title": "T", "description": "D"},
        )
        config = make_test_config()
        config.enable_content_fetch = True
        with patch(
            "metadata_enricher.enrichers.content_fetcher.fetch_page_content",
            side_effect=RuntimeError("boom"),
        ):
            pipeline = Pipeline(config=config, llm_factory=llm_factory)
            results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].resource.fetched_content is None


class TestAggregateTokenUsage:
    """_aggregate_token_usage dedups by TokenUsage object identity — a
    single agent's LLM call produces one AgentResult per output field, all
    sharing the same TokenUsage instance (confirmed in test_base_agent.py);
    summing naively would multiply that agent's real cost by its field
    count."""

    def test_sums_usage_once_per_shared_instance(self) -> None:
        agent_a_usage = TokenUsage(prompt_tokens=100, completion_tokens=50)
        agent_b_usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        results = [
            AgentResult(field_name="titles", token_usage=agent_a_usage),
            AgentResult(field_name="descriptions", token_usage=agent_a_usage),
            AgentResult(field_name="creators", token_usage=agent_b_usage),
        ]
        total = _aggregate_token_usage(results)
        assert total.prompt_tokens == 110
        assert total.completion_tokens == 55
        assert total.total_tokens == 165

    def test_empty_list_returns_zero(self) -> None:
        assert _aggregate_token_usage([]) == TokenUsage()

    def test_failed_agent_results_contribute_zero(self) -> None:
        results = [AgentResult(field_name="titles", error="boom")]
        assert _aggregate_token_usage(results) == TokenUsage()


class TestPipelineResultTokenUsage:
    """Real pipeline run, real end-to-end token accounting — not just the
    aggregation helper in isolation."""

    def test_successful_run_reports_usage_from_a_usage_aware_client(self, tmp_path) -> None:
        class FakeLLMClientWithUsage(FakeLLMClient):
            def complete_with_usage(self, prompt, response_model, system_prompt=None, **kw):  # noqa: ANN001, ANN201
                return self.complete(prompt, response_model, system_prompt, **kw), TokenUsage(
                    prompt_tokens=20, completion_tokens=10
                )

        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        factory = lambda provider, **kw: FakeLLMClientWithUsage(  # noqa: E731
            {"fields": {"titles": [{"name": "T", "title_type": "MainTitle"}]}}
        )
        pipeline = Pipeline(config=make_test_config(), llm_factory=factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))

        assert len(results) == 1
        assert results[0].token_usage.prompt_tokens == 20
        assert results[0].token_usage.completion_tokens == 10
        assert results[0].token_usage.total_tokens == 30

    def test_client_without_usage_support_reports_zero(self, tmp_path, llm_factory) -> None:
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))

        assert len(results) == 1
        assert results[0].token_usage == TokenUsage()


class TestPipelineResultModelsUsed:
    """models_used surfaces the *resolved* model per agent (e.g. what an
    OpenRouter '~...-latest' alias actually served), keyed by agent id --
    useful for a user who wants to confirm the real version behind an
    auto-updating alias, not just the configured name."""

    def test_successful_run_reports_resolved_model_per_agent(self, tmp_path) -> None:
        class FakeLLMClientWithModel(FakeLLMClient):
            def complete_with_usage(self, prompt, response_model, system_prompt=None, **kw):  # noqa: ANN001, ANN201
                return self.complete(prompt, response_model, system_prompt, **kw), TokenUsage(
                    prompt_tokens=20, completion_tokens=10, model="deepseek/deepseek-v4-flash-2508"
                )

        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        factory = lambda provider, **kw: FakeLLMClientWithModel(  # noqa: E731
            {"fields": {"titles": [{"name": "T", "title_type": "MainTitle"}]}}
        )
        pipeline = Pipeline(config=make_test_config(), llm_factory=factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))

        assert len(results) == 1
        assert results[0].models_used == {"titles-agent": "deepseek/deepseek-v4-flash-2508"}

    def test_client_without_usage_support_reports_empty_models_used(
        self, tmp_path, llm_factory
    ) -> None:
        make_input_file(
            tmp_path,
            {"url": "https://example.com/x", "title": "T", "description": "D"},
        )
        pipeline = Pipeline(config=make_test_config(), llm_factory=llm_factory)
        results = pipeline.run(FilesystemInputSource(), pattern=str(tmp_path / "*.json"))

        assert len(results) == 1
        assert results[0].models_used == {}
