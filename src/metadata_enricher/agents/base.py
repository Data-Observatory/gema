"""Base agent for metadata enrichment — no DSPy dependency."""

from __future__ import annotations

from metadata_enricher.llm.base import LLMClient
from metadata_enricher.schemas.base import Schema
from metadata_enricher.types import AgentResult, ResourceDescription, TokenUsage


class SafeDict(dict):
    """Dict subclass returning '' for missing keys — safe str.format_map()."""

    def __missing__(self, key: str) -> str:
        return ""


class BaseAgent:
    """Agent that processes a resource through LLM and extracts structured fields."""

    def __init__(
        self,
        name: str,
        fields: list[str],
        prompt: str,
        llm_client: LLMClient,
        schema: Schema,
        system_prompt: str | None = None,
    ) -> None:
        self._name = name
        self._fields = fields
        self._prompt = prompt
        self._llm_client = llm_client
        self._schema = schema
        self._system_prompt = system_prompt

    @property
    def name(self) -> str:
        return self._name

    @property
    def fields(self) -> list[str]:
        return self._fields

    def _build_resource_dict(self, resource: ResourceDescription) -> dict[str, str]:
        """Flatten ResourceDescription to str dict, None→'', include model_extra."""
        d: dict[str, str] = {}
        for key in ("url", "title", "description", "doi", "fetched_content"):
            val = getattr(resource, key, None)
            d[key] = val if val is not None else ""
        if resource.model_extra:
            for key, val in resource.model_extra.items():
                d[key] = val if val is not None else ""
        return d

    def run(self, resource: ResourceDescription) -> list[AgentResult]:
        """Format prompt, call LLM, extract+normalize fields per schema."""
        try:
            resource_dict = self._build_resource_dict(resource)
            safe = SafeDict(resource_dict)
            formatted = self._prompt.format_map(safe)

            output_model = self._schema.output_model
            result = self._llm_client.complete(
                prompt=formatted,
                response_model=output_model,
                system_prompt=self._system_prompt,
            )

            raw_json = result.model_dump_json()
            agent_results: list[AgentResult] = []
            for field_name in self._fields:
                value = getattr(result, field_name, None)
                normalized = self._schema.normalize_field(field_name, value)
                agent_results.append(
                    AgentResult(
                        field_name=field_name,
                        value=normalized,
                        raw_llm_response=raw_json,
                        token_usage=TokenUsage(),
                    )
                )
            return agent_results
        except Exception as exc:
            return [
                AgentResult(field_name=field_name, error=str(exc)) for field_name in self._fields
            ]
