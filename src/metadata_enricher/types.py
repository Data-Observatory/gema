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
    # The provider's own resolved model id for this call (e.g. what an
    # OpenRouter "~...-latest" alias actually served) -- empty when unknown
    # (a mock/fake client, or a cache hit, which reports zero usage too).
    model: str = ""

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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _strip_curie(value: object) -> str:
    text = str(value) if value is not None else ""
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def first_type_label(types: object, default: str = "") -> str:
    """First usable type label from a JSON-LD ``@type`` value.

    Per constraint C7, every nested typed object's ``@type`` is a
    one-or-more-element array of CURIE strings (e.g. ``["schema:Person"]``),
    not a bare scalar string -- but this helper tolerates a bare string too
    (defensive, for hand-built documents or partial LLM output that hasn't
    gone through normalization yet). Returns the label after the CURIE's
    colon (e.g. ``"Person"`` from ``"schema:Person"``), or *default* if
    nothing usable is found. Shared by every exporter/enricher that needs
    to classify a nested Person/Organization/etc. node by its ``@type`` --
    comparing ``entry.get("@type") == "schema:Person"`` as a bare scalar is
    a bug once ``@type`` is an array (see exporters/croissant.py's
    ``_person_or_org``, which used to make exactly this mistake).
    """
    for t in _as_list(types):
        label = _strip_curie(t)
        if label:
            return label
    return default


def jsonld_list_unwrap(value: Any) -> list[Any]:
    """Unwrap a JSON-LD ``{"@list": [...]}`` construct to its plain list.

    Some CDIF Discovery properties (``schema:creator``, per the vendored
    schema's own field description) are order-preserving JSON-LD lists,
    represented as an object wrapping ``@list`` rather than a bare array
    (unlike e.g. ``schema:contributor``, which stays a bare array — easy to
    mix up, see constraint C4 in docs/cdif_pivot_implementation_plan.md).
    A bare list is passed through unchanged so callers don't need to know
    which shape a given document actually carries; anything else (``None``,
    a dict without ``@list``) returns ``[]``.
    """
    if isinstance(value, dict):
        inner = value.get("@list")
        return inner if isinstance(inner, list) else []
    if isinstance(value, list):
        return value
    return []
