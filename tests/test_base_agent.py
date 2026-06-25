"""Tests for BaseAgent."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from metadata_enricher.agents.base import BaseAgent
from metadata_enricher.types import AgentResult, ResourceDescription


class FakeOutput(BaseModel):
    titles: list[dict] = []
    descriptions: list[dict] = []


class FakeSchema:
    @property
    def output_model(self) -> type[FakeOutput]:
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
