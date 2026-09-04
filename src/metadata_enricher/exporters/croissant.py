"""Convert a CDIF-generated MetadataDocument into MLCommons Croissant JSON-LD.

Pure crosswalk, no LLM call -- every field below is either present verbatim
on the CDIF-generated document or it isn't; there's no judgment call an LLM
would resolve better than a lookup/fallback rule (contrast with
exporters/dataverse.py's one optional Subject-classification call, which
exists specifically because Dataverse's controlled vocabulary has no CDIF
equivalent).

Verified against the real MLCommons Croissant format specification
(NOT the earlier draft in docs/cdif_pivot_implementation_plan.md's "Q9"
section, which undercounted -- see the correction note below):

    Source: https://github.com/mlcommons/croissant/blob/main/docs/croissant-spec-1.1.md
    Commit checked: 401f6fff81db26a49c0d1704f02bffc4e4fa8fe2
    Fetched: 2026-09-04
    Croissant format version: 1.1 (conformsTo "http://mlcommons.org/croissant/1.1")

Correction vs. the plan doc's draft: the spec's "Modified and Added
Properties" section states plainly that Croissant "modifies the meaning of
[schema.org's `distribution`], and makes it required" (restricting its
values to `FileObject`/`FileSet` rather than schema.org's plain
`DataDownload`). The Q9 draft had filed `distribution` under "Croissant-
specific" alongside `citeAs`/`isLiveDataset` and never flagged it as
required. It belongs in the required set. Corrected verified lists:

    Required:    @context, @type ("sc:Dataset"), dct:conformsTo (aliased
                 "conformsTo"), name, description, license, url, creator,
                 datePublished, distribution
    Recommended: keywords, publisher, version, dateCreated, dateModified,
                 sameAs, sdLicense, inLanguage
    Croissant-specific (optional): citeAs, isLiveDataset, sdVersion

Fields with no CDIF source and deliberately left unmapped in v1 (not a
gap in this module -- there's nothing on a CDIF Discovery document to map
them from): `sdLicense` (a license for the *metadata record* itself, a
different concept from `schema:license`'s license for the *data*),
`citeAs` (a citation string/bibtex FOR the dataset -- distinct from
`schema:citation`, which is bibliography cited *by* the dataset, and not
something safe to synthesize from title/creator/date without risking a
malformed or misleading citation), `isLiveDataset` (no CDIF field signals
this), and `sdVersion` (metadata-record versioning; CDIF has no field for
it either).

``recordSet`` -- Croissant's per-column/field structure description --
is deliberately absent from the output entirely (not an empty list),
never synthesized. This is a placeholder gap, not a design choice: it is
blocked on a structure-fetcher enricher that does not exist yet (see
docs/cdif_pivot_implementation_plan.md's Backlog section, Open Questions
#10-12). Nothing in a CDIF-generated MetadataDocument describes a
dataset's column/field structure, so fabricating a recordSet from title/
description prose would be pure invention. When the structure fetcher
ships, this module will need a real ``_build_record_set`` function wired
in here alongside a `CROISSANT_CONTEXT` update (the recordSet/field/
source/extract/transform term aliases from the spec's Appendix 1 JSON-LD
context, omitted below since they'd otherwise sit unused and misleading).

Shape convention this module reads for schema:creator/publisher entries
(Person/Organization) is documented in
enrichers/identifier_enricher.py's module docstring -- the actual shape
gema's CDIF pipeline produces, not something re-derived here. Note that,
contrary to docs/cdif_pivot_implementation_plan.md's constraint C4 draft,
the *shipped* ``CDIFDiscoveryOutputModel.schema_creator`` field
(schemas/cdif/discovery/cdif_discovery.py) is a plain
``list[dict[str, Any]]``, not an object wrapping ``{"@list": [...]}`` --
confirmed against both the model definition and a real recorded golden
fixture (tests/fixtures/golden/expected/sample_input01.json). This module
reads the bare-list shape as primary, and also tolerates a
``{"@list": [...]}`` wrapper defensively in case that ever changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from metadata_enricher.types import MetadataDocument, TokenUsage

logger = logging.getLogger(__name__)

CROISSANT_VERSION = "1.1"
CROISSANT_CONFORMS_TO = "http://mlcommons.org/croissant/1.1"

# Trimmed from the spec's Appendix 1 "recommended JSON-LD context" --
# only the aliases this module actually emits. The full context also
# defines recordSet/field/source/extract/transform/... term aliases,
# left out here since nothing below emits them yet (see module docstring
# -- recordSet is deliberately absent in v1). Extend this dict, don't
# replace it, when recordSet support is added.
CROISSANT_CONTEXT: dict[str, str] = {
    "@language": "en",
    "@vocab": "http://schema.org/",
    "sc": "http://schema.org/",
    "cr": "http://mlcommons.org/croissant/",
    "dct": "http://purl.org/dc/terms/",
    "citeAs": "cr:citeAs",
    "conformsTo": "dct:conformsTo",
    "isLiveDataset": "cr:isLiveDataset",
    "sdVersion": "cr:sdVersion",
    "md5": "cr:md5",
}

# Checksum length -> (Croissant property, algorithm name), keyed by hex
# digest length. schema:distribution's own `checksum` field is a bare
# string with no algorithm tag (config/agents.yaml's prompt allows
# "MD5, SHA-1, SHA-256" -- whichever the source text mentions), so the
# algorithm is inferred from digest length rather than assumed. SHA-1
# (40 hex chars) has no Croissant-recognized property (the spec only
# defines sha256 and, via the context, md5) -- a SHA-1 checksum is
# therefore never emitted, only warned about.
_CHECKSUM_PROPERTY_BY_HEX_LENGTH: dict[int, str] = {64: "sha256", 32: "md5"}


@dataclass
class CroissantExportResult:
    """Result of to_croissant_json() -- mirrors DataverseExportResult's own
    warnings/token_usage shape for consistency across exporters."""

    croissant_json: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


def _first_identifier_url(entry: dict[str, Any]) -> str | None:
    identifiers = entry.get("schema:identifier") or []
    if identifiers and isinstance(identifiers[0], dict):
        url = identifiers[0].get("url")
        if url:
            return str(url)
    return None


def _person_or_org(entry: Any) -> dict[str, Any] | None:
    """Map a CDIF creator/contributor/publisher entry (Person or
    Organization -- see enrichers/identifier_enricher.py's module
    docstring for the shape) to a Croissant Person/Organization node.
    Returns None for anything unusable rather than raising."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not name:
        return None
    node: dict[str, Any] = {
        "@type": "sc:Person" if entry.get("@type") == "schema:Person" else "sc:Organization",
        "name": name,
    }
    url = _first_identifier_url(entry)
    if url:
        node["url"] = url
    return node


def _as_entry_list(raw: Any) -> list[Any]:
    """schema:creator's shipped shape is a bare list (see module
    docstring) -- tolerate a {"@list": [...]} wrapper too, defensively."""
    if isinstance(raw, dict):
        return list(raw.get("@list") or [])
    if isinstance(raw, list):
        return raw
    return []


def _build_name(document: MetadataDocument, warnings: list[str]) -> str:
    name = document.get_field("schema:name")
    if name:
        return str(name)
    warnings.append(
        "no schema:name found — Croissant requires name; using the resource identifier "
        "as a fallback"
    )
    for entry in document.get_field("schema:identifier") or []:
        if isinstance(entry, dict) and entry.get("value"):
            return str(entry["value"])
    return "Untitled resource"


def _build_description(document: MetadataDocument, warnings: list[str]) -> str:
    description = document.get_field("schema:description")
    if description:
        return str(description)
    warnings.append("no schema:description found — Croissant requires description; using a placeholder")
    return "No description was extracted for this resource."


def _build_license(document: MetadataDocument, warnings: list[str]) -> list[str]:
    raw = document.get_field("schema:license") or []
    values: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        name = entry.get("name")
        if url:
            values.append(str(url))
        elif name:
            values.append(str(name))
    if not values:
        warnings.append(
            "no schema:license found — Croissant requires license; omitting the field "
            "rather than fabricating a legal claim"
        )
    return values


def _build_url(document: MetadataDocument, warnings: list[str]) -> str | None:
    url = document.get_field("schema:url")
    if url:
        return str(url)
    for entry in document.get_field("schema:identifier") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("propertyID", "")).upper() == "DOI" and entry.get("value"):
            return f"https://doi.org/{entry['value']}"
        if entry.get("url"):
            return str(entry["url"])
    warnings.append(
        "no schema:url or resolvable schema:identifier found — Croissant requires url; "
        "omitting the field"
    )
    return None


def _build_creators(document: MetadataDocument, warnings: list[str]) -> list[dict[str, Any]]:
    entries = _as_entry_list(document.get_field("schema:creator"))
    creators = [c for c in (_person_or_org(entry) for entry in entries) if c is not None]
    if not creators:
        warnings.append(
            "no schema:creator found — Croissant requires creator; omitting the field "
            "rather than fabricating an author"
        )
    return creators


def _build_date_published(document: MetadataDocument, warnings: list[str]) -> str | None:
    date_published = document.get_field("schema:datePublished")
    if date_published:
        return str(date_published)
    date_created = document.get_field("schema:dateCreated")
    if date_created:
        warnings.append(
            "no schema:datePublished found — falling back to schema:dateCreated for "
            "Croissant's required datePublished"
        )
        return str(date_created)
    warnings.append(
        "no schema:datePublished or schema:dateCreated found — Croissant requires "
        "datePublished; omitting the field rather than fabricating a date"
    )
    return None


def _detect_checksum(checksum: str) -> tuple[str, str] | None:
    checksum = checksum.strip()
    if not checksum or not all(c in "0123456789abcdefABCDEF" for c in checksum):
        return None
    property_name = _CHECKSUM_PROPERTY_BY_HEX_LENGTH.get(len(checksum))
    return (property_name, checksum.lower()) if property_name else None


def _build_distribution(document: MetadataDocument, warnings: list[str]) -> list[dict[str, Any]]:
    raw = document.get_field("schema:distribution") or []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content_url = item.get("contentUrl")
        if not content_url:
            continue
        file_object: dict[str, Any] = {
            "@type": "cr:FileObject",
            # contentUrl doubles as @id -- IDs are interpreted as IRIs per
            # the spec's "ID and Reference Mechanism" section, and a
            # content URL is guaranteed unique across distribution entries
            # unlike anything else this shape offers.
            "@id": str(content_url),
            "contentUrl": str(content_url),
        }
        encoding_format = item.get("encodingFormat")
        if encoding_format:
            file_object["encodingFormat"] = encoding_format
        content_size = item.get("contentSize") or []
        if content_size and isinstance(content_size[0], dict) and content_size[0].get("size") is not None:
            size, unit = content_size[0]["size"], content_size[0].get("unit", "")
            file_object["contentSize"] = f"{size} {unit}".strip()
        checksum = item.get("checksum")
        if checksum:
            detected = _detect_checksum(str(checksum))
            if detected:
                file_object[detected[0]] = detected[1]
            else:
                warnings.append(
                    f"schema:distribution entry for {content_url} has a checksum that isn't "
                    "recognizable as md5/sha256 by length — not emitted, to avoid mislabeling "
                    "its algorithm"
                )
        entries.append(file_object)
    if not entries:
        warnings.append(
            "no usable schema:distribution entries found — Croissant requires distribution "
            "(see spec's 'Modified and Added Properties' section); omitting the field"
        )
    return entries


def _build_keywords(document: MetadataDocument) -> list[str]:
    keywords = document.get_field("schema:keywords") or []
    return [k["name"] for k in keywords if isinstance(k, dict) and k.get("name")]


def _build_publisher(document: MetadataDocument) -> dict[str, Any] | None:
    raw = document.get_field("schema:publisher")
    if isinstance(raw, list):  # defensive: tolerate an overflow-shaped list too
        raw = raw[0] if raw else None
    return _person_or_org(raw) if isinstance(raw, dict) else None


def _build_same_as(document: MetadataDocument) -> list[str]:
    raw = document.get_field("schema:sameAs") or []
    values: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            candidate = entry.get("value") or entry.get("url") or entry.get("@id")
            if candidate:
                values.append(str(candidate))
        elif isinstance(entry, str) and entry:
            values.append(entry)
    return values


def to_croissant_json(document: MetadataDocument) -> CroissantExportResult:
    """Convert *document* (a CDIF Discovery-shaped MetadataDocument) into
    MLCommons Croissant JSON-LD, top-level Dataset fields only -- see the
    module docstring for the verified field list, what's deliberately
    unmapped, and why recordSet ships empty/absent.

    Never raises: every field has a graceful fallback or is simply
    omitted with a warning appended to the result. token_usage is always
    zero -- this is a pure crosswalk, no LLM call is made (kept on the
    result only for shape parity with the other exporters).
    """
    warnings: list[str] = []

    croissant: dict[str, Any] = {
        "@context": dict(CROISSANT_CONTEXT),
        "@type": "sc:Dataset",
        "conformsTo": CROISSANT_CONFORMS_TO,
        "name": _build_name(document, warnings),
        "description": _build_description(document, warnings),
    }

    resource_id = document.get_field("@id")
    if resource_id:
        croissant["@id"] = str(resource_id)

    license_values = _build_license(document, warnings)
    if license_values:
        croissant["license"] = license_values

    url = _build_url(document, warnings)
    if url:
        croissant["url"] = url

    creators = _build_creators(document, warnings)
    if creators:
        croissant["creator"] = creators

    date_published = _build_date_published(document, warnings)
    if date_published:
        croissant["datePublished"] = date_published

    distribution = _build_distribution(document, warnings)
    if distribution:
        croissant["distribution"] = distribution

    # -- Recommended --
    keywords = _build_keywords(document)
    if keywords:
        croissant["keywords"] = keywords

    publisher = _build_publisher(document)
    if publisher:
        croissant["publisher"] = publisher

    version = document.get_field("schema:version")
    if version:
        croissant["version"] = str(version)

    date_created = document.get_field("schema:dateCreated")
    if date_created:
        croissant["dateCreated"] = str(date_created)

    date_modified = document.get_field("schema:dateModified")
    if date_modified:
        croissant["dateModified"] = str(date_modified)

    same_as = _build_same_as(document)
    if same_as:
        croissant["sameAs"] = same_as

    in_language = document.get_field("schema:inLanguage")
    if in_language:
        croissant["inLanguage"] = str(in_language)

    # -- recordSet: deliberately absent, see module docstring --

    return CroissantExportResult(croissant_json=croissant, warnings=warnings, token_usage=TokenUsage())
