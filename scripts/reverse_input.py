"""Reverse-input extraction — derive the minimal user-facing input a real end
user would plausibly hand in, from a full production metadata record.

Deliberately corpus-agnostic and NOT named after any specific corpus this is
standard practice for testing an enrichment pipeline: the input must never
leak a field only the enrichment pipeline itself should be producing, or the
eval stops measuring enrichment at all. See ALLOWED_KEYS below for the exact,
explicit boundary.
"""

from __future__ import annotations

from typing import Any

# The only fields a real end user would plausibly hand in themselves, plus
# fetched_content — not something a *user* types, but the real production
# pipeline reads it too (see agents/base.py's _build_resource_dict), so it's
# not an enrichment-target leak, just the same live page context a real run
# would have. Several fields (dates, media_files, related_identifiers) live
# only on the destination page, never in a short title/description — giving
# the model that context is fair, not cheating; see scripts/fetch_content.py.
ALLOWED_KEYS = {"url", "title", "description", "publisher", "fetched_content"}

# Enrichment targets — must NEVER appear in a generated input. Not exhaustive
# by construction (ALLOWED_KEYS above is the real gate, an allow-list); this
# set exists for the self-check's "did something leak" scan in
# generate_inputs.py, covering every field any agent in config/agents.yaml is
# responsible for producing, across both the current schema's field names and
# the do_catalog ground truth's legacy names (roles, flat geo/temporal).
FORBIDDEN_KEYS = {
    "roles", "creators", "contributors", "subjects", "categories", "rights",
    "geo_locations", "temporal_events", "temporal_geo", "dates", "languages",
    "media_files", "audiences", "funding_references", "citations",
    "alternate_identifiers", "related_identifiers", "origin_name", "origin_priority",
}


def unwrap_attributes(raw: dict[str, Any]) -> dict[str, Any]:
    """Handle both metadata.attributes-wrapped (older Geoportal-style exports)
    and flat (do_catalog) ground-truth shapes — confirmed empirically that
    do_catalog files are always flat (40/40 sampled), but never assume a
    corpus's shape without checking, so both are handled here."""
    metadata = raw.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("attributes"), dict):
        attrs: dict[str, Any] = metadata["attributes"]
        return attrs
    return raw


def select_description(
    descriptions: list[dict[str, Any]], preferred_type: str = "Abstract"
) -> tuple[str, bool]:
    """Prefer the *preferred_type*-typed entry (case-insensitive); fall back
    to descriptions[0]. Returns (text, used_fallback) so callers can warn
    when no matching entry exists, instead of silently relying on ordering
    that isn't guaranteed across the whole corpus."""
    for d in descriptions:
        if str(d.get("description_type", "")).strip().lower() == preferred_type.lower():
            return str(d.get("description", "")), False
    if descriptions:
        return str(descriptions[0].get("description", "")), True
    return "", True


def extract_minimal_input(
    attrs: dict[str, Any], fetched_content: str | None = None
) -> dict[str, str]:
    """The reverse-input extractor. Returns {url, title, description,
    publisher} plus fetched_content when given — everything else is an
    enrichment target the pipeline must derive itself, never something
    handed to it as input."""
    resource = attrs.get("resource") or {}
    titles = attrs.get("titles") or [{}]
    publishers = attrs.get("publishers") or [{}]
    description, _used_fallback = select_description(attrs.get("descriptions") or [])
    result = {
        "url": str(resource.get("identifier", "")),
        "title": str(titles[0].get("name", "")),
        "description": description,
        "publisher": str(publishers[0].get("publisher_name", "")),
    }
    if fetched_content:
        result["fetched_content"] = fetched_content
    return result
