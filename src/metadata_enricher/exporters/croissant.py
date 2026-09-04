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
    Commit checked: 0e5dcb796dba285b396011638a68909c78a39664 (last commit to touch
      this file as of the fetch date below -- an earlier citation of this pin
      wrongly named a commit that only touched README.md, not the spec itself;
      corrected 2026-09-04, see docs/cdif_pivot_implementation_plan.md)
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
`dcterms:bibliographicCitation` (Open Question #19's resolution, replacing
the earlier, SHACL-forbidden `schema:citation`), which is bibliography
cited *by* the dataset, and not something safe to synthesize from
title/creator/date without risking a malformed or misleading citation),
`isLiveDataset` (no CDIF field signals
this), and `sdVersion` (metadata-record versioning; CDIF has no field for
it either).

``recordSet`` -- Croissant's per-column/field structure description --
is deliberately absent from the output entirely (not an empty list),
never synthesized. Its absence is fully spec-conformant (``recordSet`` is
optional in Croissant 1.1, not required) -- this is not a gap being
carried, just nothing to fill it with yet: it is blocked on a
structure-fetcher enricher that does not exist yet (see
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

from metadata_enricher.types import (
    MetadataDocument,
    TokenUsage,
    entity_identifiers,
    first_type_label,
    jsonld_list_unwrap,
)

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


def _as_list(value: Any) -> list[Any]:
    """gema's own generation always produces license/keywords/sameAs as a
    list (see config/agents.yaml's prompts) -- but the vendored schema
    itself allows some of these (schema:license especially) as a bare
    string or single object too. Iterating an un-guarded string silently
    walks its characters instead of raising, so a hand-built or
    differently-shaped document would produce an empty/wrong result with
    no indication why. Same shape of guard as exporters/datacite.py's own
    ``_as_list``."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


@dataclass
class CroissantExportResult:
    """Result of to_croissant_json() -- mirrors DataverseExportResult's own
    warnings/token_usage shape for consistency across exporters."""

    croissant_json: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


def _first_identifier_url(entry: dict[str, Any]) -> str | None:
    # schema:identifier is singular on a Person/Organization entry as of
    # Open Question #16 (docs/cdif_pivot_implementation_plan.md); any
    # additional resolved identifier lives in schema:sameAs. Only the
    # preferred (first) one is needed here.
    identifiers = entity_identifiers(entry)
    if identifiers:
        url = identifiers[0].get("schema:url")
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
    name = entry.get("schema:name")
    if not name:
        return None
    # first_type_label handles @type as a one-or-more-element array (C7)
    # -- comparing entry.get("@type") == "schema:Person" as a bare scalar
    # misclassified every Person as an Organization once @type became an
    # array; see types.first_type_label's docstring.
    node: dict[str, Any] = {
        "@type": "sc:Person" if first_type_label(entry.get("@type")) == "Person" else "sc:Organization",
        "name": name,
    }
    url = _first_identifier_url(entry)
    if url:
        node["url"] = url
    return node


def _as_entry_list(raw: Any) -> list[Any]:
    """schema:creator is a {"@list": [...]} JSON-LD construct as of
    ``CDIFDiscoveryProfile.merge_agent_results`` (constraint C4) -- a bare
    list is also accepted, for synthetic test fixtures or documents built
    without going through that merge step. See
    ``types.jsonld_list_unwrap``, which this delegates to."""
    return jsonld_list_unwrap(raw)


def _build_name(document: MetadataDocument, warnings: list[str]) -> str:
    name = document.get_field("schema:name")
    if name:
        return str(name)
    warnings.append(
        "no schema:name found — Croissant requires name; using the resource identifier "
        "as a fallback"
    )
    for entry in _as_list(document.get_field("schema:identifier")):
        if isinstance(entry, dict) and entry.get("schema:value"):
            return str(entry["schema:value"])
    return "Untitled resource"


def _build_description(document: MetadataDocument, warnings: list[str]) -> str:
    description = document.get_field("schema:description")
    if description:
        return str(description)
    warnings.append("no schema:description found — Croissant requires description; using a placeholder")
    return "No description was extracted for this resource."


def _build_license(document: MetadataDocument, warnings: list[str]) -> list[str]:
    values: list[str] = []
    for entry in _as_list(document.get_field("schema:license")):
        if isinstance(entry, dict):
            url = entry.get("schema:url") or entry.get("@id")
            name = entry.get("schema:name")
            if url:
                values.append(str(url))
            elif name:
                values.append(str(name))
        elif isinstance(entry, str) and entry.strip():
            # The vendored schema allows schema:license as a bare string
            # or {"@id": ...} -- gema's own generation always produces the
            # dict shape above, but this is cheap to also accept.
            values.append(entry.strip())
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
    for entry in _as_list(document.get_field("schema:identifier")):
        if not isinstance(entry, dict):
            continue
        # Prefer a URL already recorded on the identifier entry itself --
        # safer than constructing one from a bare value, and checked
        # before the DOI-specific branch below regardless of propertyID
        # (docs/cdif_pivot_implementation_plan.md Backlog: "prefer
        # schema:url on the identifier entry ... before falling back to
        # constructing one").
        entry_url = entry.get("schema:url")
        if entry_url:
            return str(entry_url)
        if str(entry.get("schema:propertyID", "")).upper() == "DOI" and entry.get("schema:value"):
            value = str(entry["schema:value"])
            # Guard against double-prefixing: entry["schema:value"] is
            # normally a bare DOI ("10.5880/..."), but nothing enforces
            # that upstream -- if it's already a full URL, use it as-is
            # rather than producing "https://doi.org/https://doi.org/...".
            if value.startswith(("http://", "https://")):
                return value
            return f"https://doi.org/{value}"
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
        content_url = item.get("schema:contentUrl")
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
        encoding_format = item.get("schema:encodingFormat")
        if encoding_format:
            file_object["encodingFormat"] = encoding_format
        # NOTE: "size"/"unit" (inside each schema:contentSize entry) and
        # "checksum" are read bare -- neither has a vendored CDIF shape at
        # all (schema:contentSize is a plain Text value in schema.org, not
        # this nested object; checksum wants a nested spdx:checksum
        # object). Left as-is; see docs/cdif_pivot_implementation_plan.md.
        # config/agents.yaml's media_files prompt emits schema:contentSize
        # as a single dict ({"size": ..., "unit": ...}) when populated, an
        # empty list when not -- both shapes are handled here (indexing a
        # dict by 0 raises KeyError, a real bug this used to hit).
        content_size = item.get("schema:contentSize")
        if isinstance(content_size, list):
            content_size = content_size[0] if content_size else None
        if isinstance(content_size, dict) and content_size.get("size") is not None:
            size, unit = content_size["size"], content_size.get("unit", "")
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
    keywords = _as_list(document.get_field("schema:keywords"))
    return [k["schema:name"] for k in keywords if isinstance(k, dict) and k.get("schema:name")]


def _build_publisher(document: MetadataDocument) -> dict[str, Any] | None:
    raw = document.get_field("schema:publisher")
    if isinstance(raw, list):  # defensive: tolerate an overflow-shaped list too
        raw = raw[0] if raw else None
    return _person_or_org(raw) if isinstance(raw, dict) else None


def _build_same_as(document: MetadataDocument) -> list[str]:
    values: list[str] = []
    for entry in _as_list(document.get_field("schema:sameAs")):
        if isinstance(entry, dict):
            candidate = entry.get("schema:value") or entry.get("schema:url") or entry.get("@id")
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
