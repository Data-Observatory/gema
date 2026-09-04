"""Convert a CDIF-generated MetadataDocument into DataCite 4.6's native shape.

``DataCiteSchema46`` (``schemas/datacite.py``) was deregistered as a
generation target when this repo pivoted to the CDIF Discovery profile
(``docs/cdif_pivot_implementation_plan.md`` Step 2) but is kept alive
specifically to be an *export* target -- this module is that exporter.

This is emphatically NOT "run DataCiteSchema46's normalizers on the CDIF
document and call it done". Those normalizers coerce a decade of loosely
-shaped legacy DataCite-agent output (multiple historical key aliases,
bare strings, etc.) into DataCite's fixed shape -- they have no idea how
to read a `schema:creator` `{"@list": [...]}` object or turn
`schema:dateModified` into DataCite's `dates[]` + `resource.publication_year`.
The real work here is the CDIF -> DataCite field mapping below, built by
reading ``docs/cdif_pivot_implementation_plan.md``'s "Q2 -- Verified
DataCite -> CDIF field mapping" table *in reverse*. ``DataCiteSchema46``'s
normalizers are used only as the LAST step: each mapped field's raw,
pre-normalization value (the same loosely-typed shape an agent's
structured output would have produced) is run through
``DataCiteSchema46.normalize_field`` / ``validate_output`` so the emitted
JSON gets DataCite's own validation, defaulting, and (notably) its
intentional ``"Collections"`` capital-C behavior for free, instead of
duplicating that logic here.

Mirrors ``exporters/dataverse.py``'s contract: function-based module,
never-throw-always-warn, a plain result dataclass. No LLM call --
Open Question #8 in the plan doc resolves to "none, pure crosswalk";
``token_usage`` stays zero but is kept for shape-parity with the other
exporters (dataverse's optional Subject-classification call, and any
future exporter that does need one).

Shape conventions read from ``enrichers/identifier_enricher.py``'s module
docstring: creator/contributor/publisher/funder entries are
Person/Organization dicts carrying ``schema:identifier`` (a list of
PropertyValue dicts: ``propertyID``/``value``/``url``), and
``schema:funding`` entries are MonetaryGrant dicts nesting a ``funder``
Organization. ``schema:creator`` is a ``{"@list": [...]}``-wrapped list,
per the vendored CDIF schema.json's own field description ("Uset the
JSON-LD @list construct to preserve author order") -- ``CDIFDiscoveryProfile
.merge_agent_results`` wraps it at generation time; a bare list is also
accepted here, for synthetic fixtures or documents built without going
through that merge step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from metadata_enricher.schemas.datacite import DataCiteOutputModel, DataCiteSchema46
from metadata_enricher.types import MetadataDocument, TokenUsage, jsonld_list_unwrap

# ----------------------------------------------------------------------
# DataCiteSchema46 singleton (Open Question resolved here, see
# docs/cdif_pivot_implementation_plan.md Step 3).
#
# DataCiteSchema46.__init__ eagerly parses a ~505KB bundled IANA MIME-type
# JSON file (IANANormalizer). Before the CDIF pivot this cost was paid
# once because schemas/__init__.py's SchemaRegistry held one process-wide
# instance. Now that DataCiteSchema46 is deregistered, nothing caches an
# instance any more -- so this module owns its own module-level singleton,
# lazily constructed on first use, instead of instantiating one per
# to_datacite_json() call (which would re-parse the IANA file every time a
# batch export runs).
# ----------------------------------------------------------------------
_datacite_schema_instance: DataCiteSchema46 | None = None


def _get_datacite_schema() -> DataCiteSchema46:
    global _datacite_schema_instance
    if _datacite_schema_instance is None:
        _datacite_schema_instance = DataCiteSchema46()
    return _datacite_schema_instance


@dataclass
class DataCiteExportResult:
    """Result of to_datacite_json() -- mirrors DataverseExportResult's
    warnings/token_usage shape for consistency across exporters."""

    datacite_json: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


# ------------------------------------------------------------------
# Small shared helpers
# ------------------------------------------------------------------


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _creator_list(value: object) -> list[dict[str, Any]]:
    """``schema:creator`` is a ``{"@list": [...]}`` JSON-LD construct as of
    ``CDIFDiscoveryProfile.merge_agent_results`` (constraint C4) -- a bare
    list is also accepted, for synthetic test fixtures or documents built
    without going through that merge step. See
    ``types.jsonld_list_unwrap``, which this delegates to."""
    return jsonld_list_unwrap(value)


def _strip_curie(value: object) -> str:
    text = str(value) if value is not None else ""
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _first_type_label(types: object, default: str = "Organization") -> str:
    for t in _as_list(types):
        label = _strip_curie(t)
        if label:
            return label
    return default


def _identifier_entries(entries: object) -> list[dict[str, Any]]:
    """``schema:identifier`` PropertyValue list -> DataCite's
    ``name_identifiers``/``funder_identifiers`` shape."""
    out: list[dict[str, Any]] = []
    for entry in _as_list(entries):
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if not value:
            continue
        out.append(
            {
                "name_identifier": value,
                "name_identifier_scheme": entry.get("propertyID", ""),
                "scheme_uri": entry.get("url", ""),
            }
        )
    return out


def _preferred_identifier(entries: object) -> tuple[str, str, str]:
    """(value, scheme, url) for the singular identifier slots
    (publisher_identifier, affiliation_identifier) -- first entry wins."""
    for entry in _as_list(entries):
        if isinstance(entry, dict) and entry.get("value"):
            return str(entry["value"]), str(entry.get("propertyID", "")), str(entry.get("url", ""))
    return "", "", ""


def _year_from_date(value: object) -> str:
    text = str(value) if value else ""
    prefix = text[:4]
    return prefix if prefix.isdigit() else ""


# ------------------------------------------------------------------
# resource
# ------------------------------------------------------------------

# Known schema:contributor roles that fold into DataCite's singular
# resource.* actor slots instead of becoming standalone creator entries.
_RESOURCE_ROLE_MAP: dict[str, str] = {
    "Producer": "producer",
    "ContactPerson": "contact",
    "Editor": "editor",
    "Maintainer": "maintainer",
}


def _identifier_and_type(document: MetadataDocument) -> tuple[str, str]:
    identifiers = _as_list(document.get_field("schema:identifier"))
    for entry in identifiers:
        if isinstance(entry, dict) and str(entry.get("propertyID", "")).upper() == "DOI":
            value = entry.get("value")
            if value:
                return str(value), "DOI"
    for entry in identifiers:
        if isinstance(entry, dict) and entry.get("value"):
            return str(entry["value"]), str(entry.get("propertyID", "")) or "URL"
    envelope_id = document.get_field("@id")
    if envelope_id:
        return str(envelope_id), "URL"
    return "", ""


def _contact_string(entry: dict[str, Any]) -> str:
    name = str(entry.get("name") or "").strip()
    email = str(entry.get("email") or "").strip()
    if name and email:
        return f"{name} ({email})"
    return name or email


def _build_resource(
    document: MetadataDocument, warnings: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Returns (raw resource dict, leftover schema:contributor entries
    whose role isn't one of the known resource.* slots -- the caller
    folds those into creators instead of silently dropping them)."""
    identifier, identifier_type = _identifier_and_type(document)
    if not identifier:
        warnings.append(
            "no schema:identifier or @id found -- resource.identifier will be empty"
        )

    resource_type_general = _first_type_label(document.get_field("@type"), default="")
    publication_year = _year_from_date(
        document.get_field("schema:datePublished") or document.get_field("schema:dateCreated")
    )

    resource: dict[str, Any] = {
        "identifier": identifier,
        "identifier_type": identifier_type,
        "editor": "",
        "maintainer": "",
        "contact": "",
        "producer": "",
        "publication_year": publication_year,
        "resource_type": document.get_field("schema:additionalType") or "",
        "resource_type_general": resource_type_general,
        "version": document.get_field("schema:version") or "",
        "thumbnail": "",
        "language": document.get_field("schema:inLanguage") or "",
    }

    for entry in _as_list(document.get_field("schema:relatedLink")):
        if not isinstance(entry, dict):
            continue
        if entry.get("linkRelationship") == "thumbnail":
            target = entry.get("target") or {}
            if isinstance(target, dict) and target.get("url"):
                resource["thumbnail"] = target["url"]

    leftover_contributors: list[dict[str, Any]] = []
    seen_roles: dict[str, list[str]] = {}
    for entry in _as_list(document.get_field("schema:contributor")):
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        slot = _RESOURCE_ROLE_MAP.get(role)
        if slot is None:
            leftover_contributors.append(entry)
            continue
        value = _contact_string(entry) if slot == "contact" else str(entry.get("name") or "")
        if not value:
            continue
        if resource[slot]:
            seen_roles.setdefault(slot, []).append(value)
            continue
        resource[slot] = value

    for slot, extra_values in seen_roles.items():
        warnings.append(
            f"multiple schema:contributor entries mapped to resource.{slot}; "
            f"kept the first, ignored: {', '.join(extra_values)}"
        )

    return resource, leftover_contributors


# ------------------------------------------------------------------
# titles / descriptions / languages
# ------------------------------------------------------------------


def _build_titles(document: MetadataDocument, warnings: list[str]) -> list[dict[str, Any]]:
    name = document.get_field("schema:name")
    language = document.get_field("schema:inLanguage") or ""
    if not name:
        warnings.append("no schema:name found -- DataCite requires at least one title")
        return []
    return [{"name": str(name), "title_type": "MainTitle", "language": language}]


def _build_descriptions(document: MetadataDocument, warnings: list[str]) -> list[dict[str, Any]]:
    descriptions: list[dict[str, Any]] = []
    language = document.get_field("schema:inLanguage") or ""
    description = document.get_field("schema:description")
    if description:
        descriptions.append(
            {"description": str(description), "description_type": "Abstract", "language": language}
        )
    else:
        warnings.append("no schema:description found")

    for technique in _as_list(document.get_field("schema:measurementTechnique")):
        if technique:
            descriptions.append(
                {"description": str(technique), "description_type": "Methods", "language": language}
            )

    return descriptions


def _build_languages(document: MetadataDocument) -> list[dict[str, Any]]:
    languages: list[dict[str, Any]] = []
    primary = document.get_field("schema:inLanguage")
    if primary:
        languages.append({"lang_code": str(primary)})
    # Overflow slot per the Q2 mapping's C2 constraint -- not produced by
    # CDIFDiscoveryProfile today, read defensively in case a hand-built or
    # future document carries it.
    for extra in _as_list(document.get_field("dcterms:language")):
        if extra:
            languages.append({"lang_code": str(extra)})
    return languages


# ------------------------------------------------------------------
# creators / publishers
# ------------------------------------------------------------------


def _affiliations_from(entries: object) -> list[dict[str, Any]]:
    affiliations: list[dict[str, Any]] = []
    for entry in _as_list(entries):
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        aff_id, aff_scheme, _aff_url = _preferred_identifier(entry.get("schema:identifier"))
        affiliations.append(
            {
                "affiliation": entry["name"],
                "affiliation_identifier": aff_id,
                "affiliation_identifier_scheme": aff_scheme,
            }
        )
    return affiliations


def _build_creators(
    document: MetadataDocument, leftover_contributors: list[dict[str, Any]], warnings: list[str]
) -> list[dict[str, Any]]:
    creators: list[dict[str, Any]] = []

    for entry in _creator_list(document.get_field("schema:creator")):
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        type_label = _first_type_label(entry.get("@type"))
        creators.append(
            {
                "creator_name": entry["name"],
                "creator_name_type": "Personal" if type_label == "Person" else "Organizational",
                "given_name": entry.get("given_name", ""),
                "family_name": entry.get("family_name", ""),
                "email": entry.get("email", ""),
                "type": type_label,
                "contributor_type": "",
                "name_identifiers": _identifier_entries(entry.get("schema:identifier")),
                "affiliations": _affiliations_from(entry.get("schema:affiliation")),
            }
        )

    if not creators:
        warnings.append("no schema:creator entries found")

    # Contributors whose role didn't map to a resource.* slot (see
    # _RESOURCE_ROLE_MAP) aren't dropped -- DataCite has nowhere purpose
    # -built for an arbitrary role, so they surface as extra creator
    # entries carrying their role in contributor_type (Q2 mapping:
    # creators[].contributor_type <- schema:contributor Role{roleName}).
    for entry in leftover_contributors:
        name = entry.get("name")
        role = entry.get("role") or ""
        if not name:
            continue
        warnings.append(
            f"schema:contributor entry with unmapped role {role!r} folded into "
            f"creators as contributor_type (name={name!r})"
        )
        creators.append(
            {
                "creator_name": name,
                "creator_name_type": "Organizational",
                "given_name": "",
                "family_name": "",
                "email": entry.get("email", ""),
                "type": "Organization",
                "contributor_type": role,
                "name_identifiers": [],
                "affiliations": [],
            }
        )

    return creators


def _build_publishers(document: MetadataDocument) -> list[dict[str, Any]]:
    publishers: list[dict[str, Any]] = []

    publisher = document.get_field("schema:publisher")
    if isinstance(publisher, dict) and publisher.get("name"):
        pub_id, pub_scheme, pub_scheme_uri = _preferred_identifier(
            publisher.get("schema:identifier")
        )
        publishers.append(
            {
                "publisher_name": publisher["name"],
                "publisher_identifier": pub_id,
                "publisher_identifier_scheme": pub_scheme,
                "publisher_scheme_uri": pub_scheme_uri,
            }
        )

    # C3 reversal: schema:provider is the array overflow slot a single
    # schema:publisher couldn't hold on the way out to CDIF -- both come
    # back into DataCite's own (always-a-list) publishers field.
    for entry in _as_list(document.get_field("schema:provider")):
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        prov_id, prov_scheme, prov_scheme_uri = _preferred_identifier(
            entry.get("schema:identifier")
        )
        publishers.append(
            {
                "publisher_name": entry["name"],
                "publisher_identifier": prov_id,
                "publisher_identifier_scheme": prov_scheme,
                "publisher_scheme_uri": prov_scheme_uri,
            }
        )

    return publishers


# ------------------------------------------------------------------
# subjects / categories / audiences
# ------------------------------------------------------------------


def _build_subjects(document: MetadataDocument) -> list[dict[str, Any]]:
    subjects: list[dict[str, Any]] = []
    for entry in _as_list(document.get_field("schema:keywords")):
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        subjects.append(
            {
                "subject_name": entry["name"],
                "subject_scheme": entry.get("inDefinedTermSet", ""),
                "value_uri": entry.get("identifier", ""),
            }
        )
    return subjects


def _build_categories(document: MetadataDocument) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    for entry in _as_list(document.get_field("schema:about")):
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        categories.append(
            {"name": entry["name"], "sub_category": entry.get("inDefinedTermSet", "")}
        )
    return categories


def _build_audiences(document: MetadataDocument) -> list[dict[str, Any]]:
    # schema:audience entries already use DataCite's own key names
    # (audience/mediator/education_level/instructional_method) -- this
    # profile's agent prompt was written to match Q2's mapping exactly,
    # so this is close to a pass-through, still filtered for junk shapes.
    return [
        entry
        for entry in _as_list(document.get_field("schema:audience"))
        if isinstance(entry, dict) and entry.get("audience")
    ]


# ------------------------------------------------------------------
# dates / temporal_events
# ------------------------------------------------------------------

_DATE_FIELD_TO_TYPE: tuple[tuple[str, str], ...] = (
    ("schema:dateCreated", "Created"),
    ("schema:datePublished", "Issued"),
    ("schema:dateModified", "Updated"),
    ("schema:copyrightYear", "Copyrighted"),
    # dcterms date terms aren't produced by CDIFDiscoveryProfile today
    # (Q2 mapping's "Inference per-term" row) -- read defensively.
    ("dcterms:dateAccepted", "Accepted"),
    ("dcterms:dateSubmitted", "Submitted"),
)


def _build_dates(document: MetadataDocument) -> list[dict[str, Any]]:
    dates: list[dict[str, Any]] = []
    for field_name, date_type in _DATE_FIELD_TO_TYPE:
        value = document.get_field(field_name)
        if value:
            dates.append({"date": str(value), "date_type": date_type})

    for interval in _as_list(document.get_field("schema:temporalCoverage")):
        if interval:
            dates.append({"date": str(interval), "date_type": "Collected"})

    for entry in _as_list(document.get_field("schema:conditionsOfAccess")):
        if isinstance(entry, dict) and entry.get("date"):
            dates.append(
                {
                    "date": str(entry["date"]),
                    "date_type": "Available",
                    "date_information": entry.get("condition", ""),
                }
            )

    return dates


def _build_temporal_events(document: MetadataDocument) -> list[dict[str, Any]]:
    # Q2 mapping's flagged judgment call: dcterms:accrualPeriodicity, not
    # produced by CDIFDiscoveryProfile today -- read defensively so a
    # hand-built/future document carrying it round-trips correctly.
    events: list[dict[str, Any]] = []
    frequency = document.get_field("dcterms:accrualPeriodicity")
    if frequency:
        events.append({"frequency_type": str(frequency)})
    return events


# ------------------------------------------------------------------
# geo_locations
# ------------------------------------------------------------------


def _build_geo_locations(document: MetadataDocument) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for entry in _as_list(document.get_field("schema:spatialCoverage")):
        if not isinstance(entry, dict) or not (entry.get("name") or entry.get("description")):
            continue
        geo = entry.get("geo") or {}
        locations.append(
            {
                "geo_location_place": entry.get("name", ""),
                "geo_location_point": geo.get("point", "") if isinstance(geo, dict) else "",
                "geo_location_box": geo.get("box", "") if isinstance(geo, dict) else "",
                "geo_description": entry.get("description", ""),
            }
        )
    return locations


# ------------------------------------------------------------------
# rights
# ------------------------------------------------------------------


def _build_rights(document: MetadataDocument) -> list[dict[str, Any]]:
    rights: list[dict[str, Any]] = []
    rights_holder = document.get_field("schema:copyrightHolder") or ""

    for entry in _as_list(document.get_field("schema:license")):
        if isinstance(entry, dict):
            rights.append(
                {
                    "rights": entry.get("name", ""),
                    "rights_uri": entry.get("url", ""),
                    "rights_identifier": entry.get("identifier", ""),
                    "rights_holder": rights_holder,
                }
            )
        elif isinstance(entry, str) and entry.strip():
            rights.append(
                {"rights": entry.strip(), "rights_uri": "", "rights_holder": rights_holder}
            )

    conditions = [
        str(entry.get("condition"))
        for entry in _as_list(document.get_field("schema:conditionsOfAccess"))
        if isinstance(entry, dict) and entry.get("condition")
    ]
    if conditions:
        combined = "; ".join(conditions)
        if rights:
            # Attach to the first entry rather than fabricating a rights
            # statement out of an access condition -- conditionsOfAccess
            # describes usage restrictions, not the license itself.
            rights[0]["rights_condition"] = combined
        else:
            rights.append(
                {"rights": "", "rights_uri": "", "rights_condition": combined, "rights_holder": rights_holder}
            )

    return rights


# ------------------------------------------------------------------
# funding_references
# ------------------------------------------------------------------


def _build_funding_references(document: MetadataDocument) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for entry in _as_list(document.get_field("schema:funding")):
        if not isinstance(entry, dict):
            continue
        funder = entry.get("funder") or {}
        award_number, _scheme, award_uri = _preferred_identifier(entry.get("identifier"))
        refs.append(
            {
                "funder_name": funder.get("name", "") if isinstance(funder, dict) else "",
                "funding_stream": entry.get("description", ""),
                "award_number": award_number,
                "award_uri": award_uri,
                "award_title": entry.get("name", ""),
                "funder_identifiers": _identifier_entries(
                    funder.get("schema:identifier") if isinstance(funder, dict) else None
                ),
            }
        )
    return refs


# ------------------------------------------------------------------
# related_identifiers / alternate_identifiers
# ------------------------------------------------------------------


def _build_related_identifiers(document: MetadataDocument) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []

    for entry in _as_list(document.get_field("schema:relatedLink")):
        if not isinstance(entry, dict):
            continue
        # thumbnail links are consumed into resource.thumbnail (_build_resource)
        # -- don't double-represent them here as a generic related identifier.
        if entry.get("linkRelationship") == "thumbnail":
            continue
        target = entry.get("target") or {}
        url = target.get("url") if isinstance(target, dict) else None
        if not url:
            continue
        related.append(
            {
                "related_identifier": url,
                "related_identifier_type": "URL",
                "relation_type": entry.get("linkRelationship", "References"),
            }
        )

    # CDIF explicitly special-cases IsDerivedFrom onto prov:wasDerivedFrom
    # rather than folding it into schema:relatedLink -- reverse that here,
    # not merged with the relatedLink loop above.
    for entry in _as_list(document.get_field("prov:wasDerivedFrom")):
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("url") or entry.get("@id")
        if not identifier:
            continue
        related.append(
            {
                "related_identifier": identifier,
                "related_identifier_type": "URL",
                "relation_type": "IsDerivedFrom",
            }
        )

    return related


def _build_alternate_identifiers(document: MetadataDocument) -> list[dict[str, Any]]:
    alternates: list[dict[str, Any]] = []
    for entry in _as_list(document.get_field("schema:sameAs")):
        if isinstance(entry, dict) and entry.get("value"):
            value = str(entry["value"])
            alternates.append(
                {
                    "alternate_name": entry.get("name", ""),
                    "alternate_identifier": value,
                    "alternate_identifier_type": "URL"
                    if value.startswith(("http://", "https://"))
                    else "Local",
                }
            )
        elif isinstance(entry, str) and entry.strip():
            alternates.append(
                {"alternate_name": "", "alternate_identifier": entry.strip(), "alternate_identifier_type": "Local"}
            )
    return alternates


# ------------------------------------------------------------------
# citations
# ------------------------------------------------------------------


def _build_citations(document: MetadataDocument) -> list[dict[str, Any]]:
    # schema:citation entries already use DataCite's own key names --
    # this profile's prompt was written to match Q2's mapping verbatim.
    return [
        entry
        for entry in _as_list(document.get_field("schema:citation"))
        if isinstance(entry, dict) and entry.get("title")
    ]


# ------------------------------------------------------------------
# media_files
# ------------------------------------------------------------------


def _build_media_files(document: MetadataDocument, warnings: list[str]) -> list[dict[str, Any]]:
    distributions = [
        entry for entry in _as_list(document.get_field("schema:distribution")) if isinstance(entry, dict)
    ]

    # Resource-level fields the CDIF generation prompt deliberately keeps
    # OUT of individual distribution entries ("a nivel del recurso, no por
    # archivo" -- config/agents.yaml's media_files agent prompt) but which
    # the Q2 mapping's DataCite direction models as per-media_files-item
    # fields. Broadcast onto every media_file entry produced below.
    variable_measured = document.get_field("schema:variableMeasured") or []
    measurement_technique = document.get_field("schema:measurementTechnique") or []
    data_quality = document.get_field("dqv:hasQualityMeasurement") or []
    provenance = document.get_field("prov:wasGeneratedBy") or {}
    top_level_collections = document.get_field("schema:includedInDataCatalog")

    if not distributions and (variable_measured or measurement_technique or data_quality or provenance):
        warnings.append(
            "resource-level media metadata (schema:variableMeasured/"
            "measurementTechnique/dqv:hasQualityMeasurement/prov:wasGeneratedBy) "
            "present but schema:distribution is empty -- nothing to attach it to"
        )

    files: list[dict[str, Any]] = []
    for entry in distributions:
        content_url = entry.get("contentUrl")
        if not content_url:
            continue
        collections_source = entry.get("schema:includedInDataCatalog") or top_level_collections
        files.append(
            {
                "file_uri": content_url,
                "format": entry.get("encodingFormat", ""),
                "sizes": entry.get("contentSize", []),
                "checksum": entry.get("checksum", ""),
                "temporal_resolution": entry.get("temporal_resolution", ""),
                "variable_measured": variable_measured,
                "measurement_technique": measurement_technique,
                "data_quality": data_quality,
                "provenance": provenance,
                "Collections": _as_list(collections_source) if collections_source else [],
            }
        )

    return files


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------


def to_datacite_json(document: MetadataDocument) -> DataCiteExportResult:
    """Convert *document* (a CDIF Discovery-shaped ``MetadataDocument``,
    CURIE-keyed) into DataCite 4.6's native dict shape.

    Pure crosswalk -- no LLM call (Open Question #8 resolved: none). Never
    raises: every builder tolerates missing/malformed input, appending a
    warning instead, and the final ``DataCiteSchema46.validate_output``
    call is wrapped so a truly malformed document degrades to an empty-ish
    but structurally valid DataCite document plus a warning rather than
    propagating a pydantic ``ValidationError`` to the caller.
    """
    warnings: list[str] = []
    schema = _get_datacite_schema()

    resource_raw, leftover_contributors = _build_resource(document, warnings)

    raw: dict[str, Any] = {
        "resource": resource_raw,
        "titles": _build_titles(document, warnings),
        "descriptions": _build_descriptions(document, warnings),
        "languages": _build_languages(document),
        "creators": _build_creators(document, leftover_contributors, warnings),
        "publishers": _build_publishers(document),
        "subjects": _build_subjects(document),
        "categories": _build_categories(document),
        "audiences": _build_audiences(document),
        "dates": _build_dates(document),
        "temporal_events": _build_temporal_events(document),
        "geo_locations": _build_geo_locations(document),
        "rights": _build_rights(document),
        "funding_references": _build_funding_references(document),
        "related_identifiers": _build_related_identifiers(document),
        "alternate_identifiers": _build_alternate_identifiers(document),
        "citations": _build_citations(document),
        "media_files": _build_media_files(document, warnings),
    }

    normalized: dict[str, Any] = {
        field_name: schema.normalize_field(field_name, value) for field_name, value in raw.items()
    }

    try:
        validated: DataCiteOutputModel = schema.validate_output(normalized)
    except Exception as exc:  # noqa: BLE001 - never propagate, degrade + warn
        warnings.append(f"DataCite validation failed, emitting an empty document: {exc}")
        validated = schema.validate_output({})

    datacite_json = validated.model_dump(exclude={"reasoning"})

    return DataCiteExportResult(datacite_json=datacite_json, warnings=warnings, token_usage=TokenUsage())
