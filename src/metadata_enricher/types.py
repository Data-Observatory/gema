"""Core domain types for metadata enrichment."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TokenUsage(BaseModel):
    """Token usage from an LLM call."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @model_validator(mode="after")
    def _calculate_total(self) -> TokenUsage:
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        return self


class ResourceDescription(BaseModel):
    """Input resource description — the source material to enrich."""

    model_config = ConfigDict(extra="allow")

    url: str | None = None
    title: str | None = None
    description: str | None = None
    doi: str | None = None
    fetched_content: str | None = None


class AgentResult(BaseModel):
    """Output from a single agent's extraction."""

    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(..., min_length=1)
    value: list[Any] | dict[str, Any] | str | None = None
    confidence: float | None = None
    raw_llm_response: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None


class MetadataDocument(BaseModel):
    """Canonical intermediate representation of metadata.

    A flexible container that schemas validate, normalize, and serialize.
    NOT DataCite-specific — schemas handle field-specific logic.
    """

    model_config = ConfigDict(extra="allow")

    fields: dict[str, Any] = Field(default_factory=dict)

    def set_field(self, name: str, value: Any) -> None:
        self.fields[name] = value

    def get_field(self, name: str, default: Any = None) -> Any:
        return self.fields.get(name, default)

    def merge(self, other: dict[str, Any]) -> None:
        """Merge a dict of agent results into this document."""
        for key, value in other.items():
            if value is not None:
                self.fields[key] = value
