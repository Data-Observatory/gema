"""Deterministic source-of-truth fields -- ``schema:name`` and ``schema:description``.

The core_metadata prompt tells the model to copy ``title`` into ``schema:name`` and
``description`` into ``schema:description`` verbatim. That is a copy, not an
extraction, so there is nothing for an LLM to add and only drift to lose: this
module enforces it in code after the merge. It acts only when the model got it
wrong, and leaves alone anything that is a legitimate sub-form of the source
(the prompt lets a bilingual title be split, main form in ``schema:name``).

* model returned nothing        -> ``filled`` from the source
* model returned text contained in the source (after accent/case/punctuation
  folding) -> kept untouched
* model returned anything else (paraphrase, translation, "cleaned" title)
  -> ``overridden`` with the source text

Every ``filled``/``overridden`` is reported, so how often the model deviates is
measurable instead of invisible.
"""

from __future__ import annotations

from typing import Literal

from metadata_enricher.enrichers.grounding import normalize_text, repair_mojibake
from metadata_enricher.types import GuardrailEvent, MetadataDocument, ResourceDescription

GUARDRAIL_NAME = "source_fields"

_SOURCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("schema:name", "title"),
    ("schema:description", "description"),
)


def enforce_source_fields(
    document: MetadataDocument, resource: ResourceDescription
) -> list[GuardrailEvent]:
    """Fill/override ``schema:name`` and ``schema:description`` in *document* in place."""
    events: list[GuardrailEvent] = []
    for field, attr in _SOURCE_FIELDS:
        raw = getattr(resource, attr, None)
        source = repair_mojibake(raw.strip()) if isinstance(raw, str) else ""
        if not source:
            continue

        current = document.get_field(field)
        action: Literal["filled", "overridden"]
        current_text = current.strip() if isinstance(current, str) else ""
        if current_text:
            if f" {normalize_text(current_text)} " in f" {normalize_text(source)} ":
                continue
            action = "overridden"
            detail = f"model output was not contained in input {attr}"
        else:
            action = "filled"
            detail = f"model returned nothing; copied from input {attr}"

        document.set_field(field, source)
        events.append(
            GuardrailEvent(
                guardrail=GUARDRAIL_NAME,
                action=action,
                field=field,
                location=field,
                value=current_text[:200],
                detail=detail,
            )
        )
    return events
