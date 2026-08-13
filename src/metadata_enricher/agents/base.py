"""Base agent for metadata enrichment — no DSPy dependency."""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from metadata_enricher.enrichers.country_extractor import CountryExtractor
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.schemas.base import Schema
from metadata_enricher.types import AgentResult, ResourceDescription, TokenUsage

logger = logging.getLogger(__name__)

# Stateless (no I/O, no config) — one shared instance for every agent/resource.
_country_extractor = CountryExtractor()


class SafeDict(dict[str, str]):
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

        # Deterministic hint from the URL/HTML — cheaper and more reliable
        # than asking the LLM to guess a country from context. An explicit
        # detected_country in the input (via model_extra below) still wins.
        detected_country = _country_extractor.extract_country(
            html_content=resource.fetched_content, url=resource.url
        )
        d["detected_country"] = detected_country or ""

        if resource.model_extra:
            for key, val in resource.model_extra.items():
                d[key] = val if val is not None else ""
        return d

    def run(self, resource: ResourceDescription) -> list[AgentResult]:
        """Format prompt, call LLM, extract+normalize fields per schema."""
        started = time.monotonic()
        logger.info("Agent '%s' starting (fields: %s)", self._name, ", ".join(self._fields))
        try:
            resource_dict = self._build_resource_dict(resource)
            formatted = self._prompt
            for key, val in resource_dict.items():
                formatted = formatted.replace("{" + key + "}", val)

            formatted += "\n\n=== RECURSO A PROCESAR ===\n"
            for key in ("url", "title", "description", "doi", "fetched_content"):
                val = resource_dict.get(key, "")
                if val:
                    formatted += f"- {key}: {val}\n"
            for key, val in resource_dict.items():
                if key not in ("url", "title", "description", "doi", "fetched_content") and val:
                    formatted += f"- {key}: {val}\n"

            # build_output_model (not the bare output_model property) so
            # this agent's own field order controls structured-output
            # decode order -- see Schema.build_output_model's docstring.
            output_model = self._schema.build_output_model(self._fields)
            # complete_with_usage is an optional, duck-typed extension of the
            # real production client chain (Instructor/Retryable/Cached) —
            # not part of the formal LLMClient Protocol, so mocks/fakes that
            # only implement complete() keep working unchanged, just without
            # real token counts (see llm/retry.py's complete_with_usage
            # docstring for the full rationale).
            complete_with_usage = getattr(self._llm_client, "complete_with_usage", None)
            if complete_with_usage is not None:
                result, token_usage = complete_with_usage(
                    prompt=formatted,
                    response_model=output_model,
                    system_prompt=self._system_prompt,
                )
            else:
                result = self._llm_client.complete(
                    prompt=formatted,
                    response_model=output_model,
                    system_prompt=self._system_prompt,
                )
                token_usage = TokenUsage()

            raw_json = result.model_dump_json()
            agent_results: list[AgentResult] = []
            for field_name in self._fields:
                value = getattr(result, field_name, None)
                normalized = self._schema.normalize_field(field_name, value)
                agent_results.append(
                    AgentResult(
                        field_name=field_name,
                        # Schema.normalize_field returns `object` by protocol
                        # contract, but always yields a JSON-shaped value here.
                        value=cast("list[Any] | dict[str, Any] | str | None", normalized),
                        raw_llm_response=raw_json,
                        token_usage=token_usage,
                    )
                )
            elapsed = time.monotonic() - started
            logger.info(
                "Agent '%s' finished in %.1fs (%d tokens)",
                self._name,
                elapsed,
                token_usage.total_tokens,
            )
            return agent_results
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.error("Agent '%s' failed after %.1fs: %s", self._name, elapsed, exc)
            return [
                AgentResult(field_name=field_name, error=str(exc)) for field_name in self._fields
            ]
