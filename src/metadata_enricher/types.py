"""Core domain types for metadata enrichment."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

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


# Open Question #22: an overflow schema:sameAs entry is a bare
# {"@id": <resolvable URL>} reference, carrying no scheme label of its own
# -- the scheme is inferred from the URL's host, the same information a
# human reading the URL would use. ROR ids are already full URIs (the
# host itself, no path segment to strip); ISNI/ORCID resolver URLs end in
# the bare id.
_SAME_AS_HOST_SCHEME: dict[str, str] = {"ror.org": "ROR", "isni.org": "ISNI", "orcid.org": "ORCID"}


def _reconstruct_identifier_from_same_as(value: object) -> dict[str, Any]:
    """Reconstructs the PropertyValue shape (``schema:propertyID`` +
    ``schema:value`` + ``schema:url``) callers of ``entity_identifiers``
    want, from a spec-legal bare ``{"@id": url}``/plain-string overflow
    entry (Open Question #22). Returns ``{}`` if *value* isn't a usable
    URL string. An unrecognized host degrades to ``{"schema:url": url}``
    (empty ``schema:propertyID``) rather than dropping the entry."""
    url = value.get("@id") if isinstance(value, dict) else value
    if not isinstance(url, str) or not url:
        return {}
    host = urlparse(url).netloc.removeprefix("www.")
    scheme = _SAME_AS_HOST_SCHEME.get(host)
    if scheme is None:
        return {"schema:url": url}
    value_part = url if scheme == "ROR" else url.rsplit("/", 1)[-1]
    return {"schema:propertyID": scheme, "schema:value": value_part, "schema:url": url}


def entity_identifiers(entry: object) -> list[dict[str, Any]]:
    """Every resolved identifier on a nested Person/Organization/MonetaryGrant
    *entry* dict (a creator/contributor-actor/publisher/funder entry).

    The vendored CDIF schema.json models ``Person``/``Organization``/
    ``MonetaryGrant``'s own ``schema:identifier`` as *singular* (one
    Identifier object, or a bare string) -- not a list. The document's own
    top-level ``schema:identifier`` is singular too as of Open Question
    #23 (CDIFDiscoveryProfile.merge_agent_results collapses it the same
    way, one level up) -- this helper is for the nested case only. See
    Open Question #16: the resolution is to write the first/preferred
    identifier as the singular ``schema:identifier`` slot and any
    additional resolved identifiers into the same entry's ``schema:sameAs``
    array -- the vendored ``Person``/``Organization`` ``$defs`` ship
    exactly that sibling array, documented there as "other identifiers for
    the organization/person". Open Question #22: that sibling array's own
    items are typed ``anyOf: [string, {"@id": string}]`` in the vendored
    ``$defs`` -- not the full PropertyValue shape ``schema:identifier``
    itself uses -- so an overflow entry is reconstructed back into that
    shape via ``_reconstruct_identifier_from_same_as`` before being
    returned.

    This reads both slots back into one flat list, preferred entry first --
    the shape every pre-#16 caller (name_identifiers, funder_identifiers,
    an author's authorIdentifier, ...) actually wants. Also tolerates a
    bare list under ``schema:identifier`` itself (the pre-#16 shape, or a
    hand-built/synthetic test fixture), and a pre-#22 full-PropertyValue-
    shaped ``schema:sameAs`` entry (already the shape callers want, passed
    through unchanged) -- so callers don't need extra code paths.
    """
    if not isinstance(entry, dict):
        return []
    out: list[dict[str, Any]] = []
    primary = entry.get("schema:identifier")
    if isinstance(primary, dict) and primary:
        out.append(primary)
    elif isinstance(primary, list):
        out.extend(item for item in primary if isinstance(item, dict) and item)
    for extra in entry.get("schema:sameAs") or []:
        if isinstance(extra, dict) and "schema:propertyID" in extra:
            out.append(extra)
        elif isinstance(extra, dict) and "@id" in extra:
            reconstructed = _reconstruct_identifier_from_same_as(extra)
            if reconstructed:
                out.append(reconstructed)
        elif isinstance(extra, str) and extra:
            reconstructed = _reconstruct_identifier_from_same_as(extra)
            if reconstructed:
                out.append(reconstructed)
    return out


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
