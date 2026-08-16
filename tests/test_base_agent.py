"""Tests for BaseAgent."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import BaseModel

from metadata_enricher.agents.base import BaseAgent
from metadata_enricher.types import AgentResult, ResourceDescription, TokenUsage


class FakeOutput(BaseModel):
    titles: list[dict] = []
    descriptions: list[dict] = []


class FakeSchema:
    @property
    def output_model(self) -> type[FakeOutput]:
        return FakeOutput

    def build_output_model(self, fields: list[str]) -> type[FakeOutput]:
        return FakeOutput

    def normalize_field(self, name: str, value: object) -> object:
        return value

    @property
    def name(self) -> str:
        return "fake"

    @property
    def version(self) -> str:
        return "1.0"


class MockLLMClient:
    def __init__(self, result: object, raise_exc: type[Exception] | None = None) -> None:
        self._result = result
        self._raise = raise_exc
        self.last_prompt: str | None = None

    @property
    def model(self) -> str:
        return "test-model"

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> object:
        if self._raise:
            raise self._raise
        self.last_prompt = prompt
        return self._result

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        return "raw"


class TestBaseAgent:
    @staticmethod
    def _make_agent(
        fields: list[str] | None = None,
        prompt: str = "Extract {title}",
        llm_result: object | None = None,
        llm_raise: type[Exception] | None = None,
        schema: object | None = None,
    ) -> BaseAgent:
        if llm_result is None:
            llm_result = FakeOutput(titles=[{"title": "T1"}], descriptions=[{"desc": "D1"}])
        if schema is None:
            schema = FakeSchema()
        client = MockLLMClient(result=llm_result, raise_exc=llm_raise)
        return BaseAgent(
            name="test-agent",
            fields=fields or ["titles", "descriptions"],
            prompt=prompt,
            llm_client=client,
            schema=schema,  # type: ignore[arg-type]
        )

    def test_run_returns_agent_results(self) -> None:
        agent = self._make_agent()
        resource = ResourceDescription(url="https://example.com", title="Test")
        results = agent.run(resource)
        assert len(results) == 2
        assert all(isinstance(r, AgentResult) for r in results)

    def test_run_extracts_correct_fields(self) -> None:
        agent = self._make_agent(fields=["titles", "descriptions"])
        resource = ResourceDescription(url="https://example.com")
        results = agent.run(resource)
        assert results[0].field_name == "titles"
        assert results[1].field_name == "descriptions"

    def test_run_normalizes_via_schema(self) -> None:
        call_log: list[tuple[str, object]] = []

        class LoggingFakeSchema(FakeSchema):
            def normalize_field(self, name: str, value: object) -> object:
                call_log.append((name, value))
                return super().normalize_field(name, value)

        agent = self._make_agent(schema=LoggingFakeSchema())
        resource = ResourceDescription(url="https://example.com")
        agent.run(resource)
        assert len(call_log) == 2
        assert call_log[0][0] == "titles"
        assert call_log[1][0] == "descriptions"

    def test_run_handles_llm_error(self) -> None:
        agent = self._make_agent(llm_raise=ValueError("LLM failed"))
        resource = ResourceDescription(url="https://example.com")
        results = agent.run(resource)
        assert len(results) == 2
        for r in results:
            assert r.error is not None
            assert "LLM failed" in r.error
            assert r.value is None

    def test_run_defaults_to_zero_usage_when_client_lacks_complete_with_usage(self) -> None:
        """MockLLMClient here only implements complete() — the fallback path
        (agents/base.py) must report TokenUsage() zeros, never guess."""
        agent = self._make_agent()
        resource = ResourceDescription(url="https://example.com")
        results = agent.run(resource)
        for r in results:
            assert r.token_usage == TokenUsage()

    def test_run_uses_real_usage_when_client_provides_it(self) -> None:
        class MockLLMClientWithUsage(MockLLMClient):
            def complete_with_usage(
                self,
                prompt: str,
                response_model: type[BaseModel],
                system_prompt: str | None = None,
                **kwargs: object,
            ) -> tuple[object, TokenUsage]:
                return self.complete(prompt, response_model, system_prompt, **kwargs), TokenUsage(
                    prompt_tokens=100, completion_tokens=50
                )

        client = MockLLMClientWithUsage(
            result=FakeOutput(titles=[{"title": "T1"}], descriptions=[{"desc": "D1"}])
        )
        agent = BaseAgent(
            name="test-agent",
            fields=["titles", "descriptions"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(url="https://example.com", title="Test")
        results = agent.run(resource)
        assert len(results) == 2
        for r in results:
            assert r.token_usage.prompt_tokens == 100
            assert r.token_usage.completion_tokens == 50
            assert r.token_usage.total_tokens == 150
        # Every field from one LLM call shares the same TokenUsage instance —
        # pipeline.py's aggregation relies on this to avoid double-counting.
        assert results[0].token_usage is results[1].token_usage

    def test_run_uses_complete_with_tools_when_agent_declares_tools(self) -> None:
        class MockLLMClientWithTools(MockLLMClient):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args, **kwargs)  # type: ignore[arg-type]
                self.received_tools: list[str] | None = None

            def complete_with_tools(
                self,
                prompt: str,
                response_model: type[BaseModel],
                tools: list[str],
                system_prompt: str | None = None,
                **kwargs: object,
            ) -> tuple[object, TokenUsage]:
                self.received_tools = tools
                return self.complete(prompt, response_model, system_prompt, **kwargs), TokenUsage(
                    prompt_tokens=7
                )

        client = MockLLMClientWithTools(
            result=FakeOutput(titles=[{"title": "T1"}], descriptions=[{"desc": "D1"}])
        )
        agent = BaseAgent(
            name="test-agent",
            fields=["titles", "descriptions"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
            tools=["lookup_organization"],
        )
        resource = ResourceDescription(url="https://example.com", title="Test")
        results = agent.run(resource)

        assert client.received_tools == ["lookup_organization"]
        assert all(r.token_usage.prompt_tokens == 7 for r in results)

    def test_run_ignores_tools_branch_when_agent_declares_no_tools(self) -> None:
        """An agent with no tools= must never call complete_with_tools, even
        if the client happens to implement it — that path is opt-in per
        agent, not automatic just because the client is capable."""

        class MockLLMClientWithTools(MockLLMClient):
            def complete_with_tools(
                self, *args: object, **kwargs: object
            ) -> tuple[object, TokenUsage]:
                raise AssertionError("complete_with_tools must not be called")

        client = MockLLMClientWithTools(
            result=FakeOutput(titles=[{"title": "T1"}], descriptions=[{"desc": "D1"}])
        )
        agent = BaseAgent(
            name="test-agent",
            fields=["titles", "descriptions"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(url="https://example.com", title="Test")
        results = agent.run(resource)
        assert len(results) == 2

    def test_run_logs_start_and_finish(self, caplog: pytest.LogCaptureFixture) -> None:
        """visor's live log console (visor/log_stream.py) surfaces exactly
        these records — without them the console looks stuck for the
        entire duration of a run with no sense of progress."""
        agent = self._make_agent()
        resource = ResourceDescription(url="https://example.com")
        with caplog.at_level(logging.INFO, logger="metadata_enricher.agents.base"):
            agent.run(resource)
        messages = [r.message for r in caplog.records]
        assert any("test-agent' starting" in m for m in messages)
        assert any("test-agent' finished" in m for m in messages)

    def test_run_logs_failure_with_elapsed_time(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = self._make_agent(llm_raise=ValueError("boom"))
        resource = ResourceDescription(url="https://example.com")
        with caplog.at_level(logging.INFO, logger="metadata_enricher.agents.base"):
            agent.run(resource)
        messages = [r.message for r in caplog.records]
        assert any("test-agent' failed" in m and "boom" in m for m in messages)

    def test_prompt_formatting_with_resource(self) -> None:
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["titles"],
            prompt="URL: {url}, Title: {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(url="https://example.org", title="Hello")
        agent.run(resource)
        assert client.last_prompt is not None
        assert "https://example.org" in client.last_prompt
        assert "Hello" in client.last_prompt

    def test_prompt_formatting_missing_keys(self) -> None:
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["titles"],
            prompt="URL: [{url}]",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(title="No URL")
        agent.run(resource)
        assert client.last_prompt is not None
        assert "URL: []" in client.last_prompt
        assert "=== RECURSO A PROCESAR ===" in client.last_prompt
        assert "- title: No URL" in client.last_prompt

    def test_upstream_fields_injected_when_context_fields_declared(self) -> None:
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["rights"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
            context_fields=["publishers"],
        )
        resource = ResourceDescription(url="https://example.com", title="Hello")
        agent.run(
            resource,
            upstream_fields={"publishers": [{"publisher_name": "ACME"}], "unrelated": "ignored"},
        )
        assert client.last_prompt is not None
        assert "DATOS YA EXTRAÍDOS EN UN PASO ANTERIOR" in client.last_prompt
        assert "publishers" in client.last_prompt
        assert "ACME" in client.last_prompt
        assert "unrelated" not in client.last_prompt

    def test_no_context_fields_ignores_upstream_fields(self) -> None:
        """An agent that never declared context_fields must not surface any
        upstream_fields, even if the orchestrator passes some."""
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["titles"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(url="https://example.com", title="Hello")
        agent.run(resource, upstream_fields={"publishers": [{"publisher_name": "ACME"}]})
        assert client.last_prompt is not None
        assert "DATOS YA EXTRAÍDOS" not in client.last_prompt

    def test_context_field_absent_from_upstream_fields_is_silently_skipped(self) -> None:
        """context_fields names a field that hasn't arrived yet (e.g. its
        upstream agent errored, or hasn't run) -- no note is added at all,
        rather than one for an empty/missing value."""
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["rights"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
            context_fields=["publishers"],
        )
        resource = ResourceDescription(url="https://example.com", title="Hello")
        agent.run(resource, upstream_fields={})
        assert client.last_prompt is not None
        assert "DATOS YA EXTRAÍDOS" not in client.last_prompt

    def test_no_upstream_fields_arg_is_backward_compatible(self) -> None:
        """Calling run() without upstream_fields at all (the pre-3c call
        shape) still works -- default None, no crash, no injected note."""
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["rights"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
            context_fields=["publishers"],
        )
        resource = ResourceDescription(url="https://example.com", title="Hello")
        results = agent.run(resource)
        assert len(results) == 1
        assert client.last_prompt is not None
        assert "DATOS YA EXTRAÍDOS" not in client.last_prompt

    def test_detected_country_from_url_appears_in_prompt(self) -> None:
        """CountryExtractor derives a country hint from the resource URL and
        it's surfaced to the LLM as extra prompt context."""
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["titles"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(url="https://datos.gob.cl/dataset/x", title="Hello")
        agent.run(resource)
        assert client.last_prompt is not None
        assert "- detected_country: CL" in client.last_prompt

    def test_explicit_detected_country_overrides_derived_value(self) -> None:
        """An explicit detected_country in the input (model_extra) wins over
        the value CountryExtractor would have derived from the URL."""
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["titles"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(
            url="https://datos.gob.cl/dataset/x", title="Hello", detected_country="AR"
        )
        agent.run(resource)
        assert client.last_prompt is not None
        assert "- detected_country: AR" in client.last_prompt

    def test_no_country_detected_omits_hint_from_prompt(self) -> None:
        """No URL/HTML to extract from -> empty hint, not printed as noise."""
        client = MockLLMClient(result=FakeOutput())
        agent = BaseAgent(
            name="test-agent",
            fields=["titles"],
            prompt="Extract {title}",
            llm_client=client,
            schema=FakeSchema(),  # type: ignore[arg-type]
        )
        resource = ResourceDescription(title="Hello")
        agent.run(resource)
        assert client.last_prompt is not None
        assert "detected_country" not in client.last_prompt

    def test_no_dspy_imports(self) -> None:
        source_path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "metadata_enricher"
            / "agents"
            / "base.py"
        )
        source = source_path.read_text()
        assert "dspy" not in source, "base.py must not import or reference dspy"

    def test_name_and_fields_properties(self) -> None:
        agent = self._make_agent(fields=["titles"])
        assert agent.name == "test-agent"
        assert agent.fields == ["titles"]
