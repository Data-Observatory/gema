"""DataCite 4.6 Schema implementation.

Migrates normalization logic from Merger to a pluggable Schema Protocol
implementation.  No dependency on the datacite PyPI library.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from metadata_enricher.enrichers.iana_normalizer import IANANormalizer
from metadata_enricher.types import AgentResult, MetadataDocument


class DataCiteOutputModel(BaseModel):
    """Validated output model for DataCite 4.6.

    All fields are optional (produced progressively by agents).  Custom
    extension fields (temporal_events, audiences, categories, citations,
    media_files) are included alongside standard DataCite properties.
    """

    model_config = {"extra": "allow"}

    resource: dict[str, Any] = Field(default_factory=dict)
    alternate_identifiers: list[dict[str, Any]] = Field(default_factory=list)
    audiences: list[dict[str, Any]] = Field(default_factory=list)
    categories: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    creators: list[dict[str, Any]] = Field(default_factory=list)
    dates: list[dict[str, Any]] = Field(default_factory=list)
    descriptions: list[dict[str, Any]] = Field(default_factory=list)
    funding_references: list[dict[str, Any]] = Field(default_factory=list)
    geo_locations: list[dict[str, Any]] = Field(default_factory=list)
    languages: list[dict[str, Any]] = Field(default_factory=list)
    media_files: list[dict[str, Any]] = Field(default_factory=list)
    publishers: list[dict[str, Any]] = Field(default_factory=list)
    related_identifiers: list[dict[str, Any]] = Field(default_factory=list)
    rights: list[dict[str, Any]] = Field(default_factory=list)
    subjects: list[dict[str, Any]] = Field(default_factory=list)
    temporal_events: list[dict[str, Any]] = Field(default_factory=list)
    titles: list[dict[str, Any]] = Field(default_factory=list)


class DataCiteSchema46:
    """DataCite Metadata Schema 4.6 implementation.

    Implements the Schema Protocol defined in metadata_enricher.schemas.base.
    Normalization logic was migrated from merger.py and preserves the original
    behaviour exactly.  Custom extension fields are first-class citizens.
    """

    def __init__(self) -> None:
        # Loads the bundled IANA snapshot once; this class is a process-wide
        # singleton (see schemas/__init__.py), so the 505KB JSON is parsed
        # exactly once per run, not per media_files normalization call.
        self._iana_normalizer = IANANormalizer()

    # ------------------------------------------------------------------
    # Language code mapping (migrated from Merger.LANG_CODE_MAP)
    # ------------------------------------------------------------------
    LANG_CODE_MAP: ClassVar[dict[str, str]] = {
        "spanish": "es",
        "español": "es",
        "espanol": "es",
        "english": "en",
        "inglés": "en",
        "ingles": "en",
        "portuguese": "pt",
        "portugués": "pt",
        "portugues": "pt",
        "french": "fr",
        "français": "fr",
        "francais": "fr",
        "german": "de",
        "deutsch": "de",
        "chinese": "zh",
        "中文": "zh",
        "japanese": "ja",
        "日本語": "ja",
        "korean": "ko",
        "한국어": "ko",
    }

    # Frequency mapping for temporal_events strings (migrated from Merger)
    _FREQ_MAP: ClassVar[dict[str, str]] = {
        "mensual": "monthly",
        "monthly": "monthly",
        "diario": "daily",
        "daily": "daily",
        "semanal": "weekly",
        "weekly": "weekly",
        "anual": "yearly",
        "yearly": "yearly",
    }

    # ------------------------------------------------------------------
    # Schema identity  (Protocol properties)
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "datacite-4.6"

    @property
    def version(self) -> str:
        return "4.6"

    @property
    def output_model(self) -> type[BaseModel]:
        return DataCiteOutputModel

    # ------------------------------------------------------------------
    # Field ordering (migrated from Merger.FIELD_ORDER)
    # ------------------------------------------------------------------

    _FIELD_ORDER: ClassVar[list[str]] = [
        "resource",
        "alternate_identifiers",
        "audiences",
        "categories",
        "citations",
        "creators",
        "dates",
        "descriptions",
        "funding_references",
        "geo_locations",
        "languages",
        "media_files",
        "publishers",
        "related_identifiers",
        "rights",
        "subjects",
        "temporal_events",
        "titles",
    ]

    def get_field_order(self) -> list[str]:
        return list(self._FIELD_ORDER)

    _REQUIRED_FIELDS: ClassVar[list[str]] = ["titles"]

    def get_required_fields(self) -> list[str]:
        return list(self._REQUIRED_FIELDS)

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate_output(self, raw: dict[str, Any]) -> DataCiteOutputModel:
        return DataCiteOutputModel(**raw)

    # ------------------------------------------------------------------
    # Normalize field  (dispatch — migrated from Merger._normalize_field)
    # ------------------------------------------------------------------

    def normalize_field(self, field_name: str, value: object) -> object:
        method_name = self._NORMALIZER_DISPATCH.get(field_name)
        if method_name is not None:
            return getattr(self, method_name)(value)
        return value

    _NORMALIZER_DISPATCH: ClassVar[dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Merge agent results
    # ------------------------------------------------------------------

    def merge_agent_results(self, results: list[AgentResult]) -> MetadataDocument:
        doc = MetadataDocument()

        for result in results:
            if result.error or result.value is None:
                continue

            field = result.field_name
            normalized = self.normalize_field(field, result.value)
            existing = doc.get_field(field)

            if existing is None:
                doc.set_field(field, normalized)
            elif isinstance(existing, list) and isinstance(normalized, list):
                doc.set_field(field, existing + normalized)
            elif isinstance(existing, dict) and isinstance(normalized, dict):
                merged = dict(existing)
                for k, v in normalized.items():
                    if k not in merged or (v and not merged.get(k)):
                        merged[k] = v
                doc.set_field(field, merged)
            else:
                doc.set_field(field, normalized)

        # Order fields
        ordered: dict[str, Any] = {}
        for field_name in self._FIELD_ORDER:
            if field_name in doc.fields:
                ordered[field_name] = doc.fields[field_name]
        for field_name in doc.fields:
            if field_name not in ordered:
                ordered[field_name] = doc.fields[field_name]
        doc.fields = ordered

        return doc

    # ------------------------------------------------------------------
    # Valid resource types  (migrated from Merger.VALID_RESOURCE_TYPES)
    # ------------------------------------------------------------------

    VALID_RESOURCE_TYPES: ClassVar[set[str]] = {
        "dataset",
        "software",
        "text",
        "image",
        "video",
        "audio",
        "collection",
        "event",
        "interactive resource",
        "model",
        "physical object",
        "service",
        "sound",
        "workflow",
        "other",
    }

    # ==================================================================
    #  Normalizer methods  (migrated from Merger)
    # ==================================================================

    # -- titles --------------------------------------------------------

    def _normalize_titles(self, value: object) -> list[dict[str, Any]]:
        titles: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for i, item in enumerate(items):
            if isinstance(item, dict):
                if "name" in item:
                    titles.append(item)
                elif "title" in item:
                    titles.append(
                        {
                            "name": item.get("title"),
                            "title_type": item.get(
                                "title_type",
                                "MainTitle" if i == 0 else "AlternativeTitle",
                            ),
                            "language": item.get("language", ""),
                        }
                    )
                else:
                    first_val = next(iter(item.values()), "")
                    titles.append(
                        {
                            "name": str(first_val),
                            "title_type": "MainTitle" if i == 0 else "AlternativeTitle",
                            "language": "",
                        }
                    )
            elif isinstance(item, str) and item.strip():
                titles.append(
                    {
                        "name": item.strip(),
                        "title_type": "MainTitle" if i == 0 else "AlternativeTitle",
                        "language": "",
                    }
                )

        return titles

    # -- descriptions --------------------------------------------------

    def _normalize_descriptions(self, value: object) -> list[dict[str, Any]]:
        descriptions: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for i, item in enumerate(items):
            if isinstance(item, dict):
                if "description" in item:
                    descriptions.append(item)
                elif "text" in item:
                    descriptions.append(
                        {
                            "description": item.get("text"),
                            "description_type": item.get("description_type", "Abstract"),
                            "language": item.get("language", ""),
                        }
                    )
                else:
                    first_val = next(iter(item.values()), "")
                    descriptions.append(
                        {
                            "description": str(first_val),
                            "description_type": "Abstract",
                            "language": "",
                        }
                    )
            elif isinstance(item, str) and item.strip():
                descriptions.append(
                    {
                        "description": item.strip(),
                        "description_type": "Abstract",
                        "language": "",
                    }
                )

        return descriptions

    # -- languages -----------------------------------------------------

    def _to_iso_lang(self, value: str) -> str:
        v = value.strip().lower()
        if v in self.LANG_CODE_MAP:
            return self.LANG_CODE_MAP[v]
        if len(v) == 2:
            return v
        return value

    def _normalize_languages(self, value: object) -> list[dict[str, Any]]:
        languages: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "lang_code" in item:
                    lang_code = self._to_iso_lang(str(item["lang_code"]))
                    languages.append(
                        {
                            "lang_code": lang_code,
                            "language": item.get("language", ""),
                            "description": item.get("description", ""),
                        }
                    )
                elif "code" in item:
                    lang_code = self._to_iso_lang(str(item.get("code", "")))
                    languages.append(
                        {
                            "lang_code": lang_code,
                            "language": item.get("language", ""),
                            "description": item.get("description", ""),
                        }
                    )
                else:
                    first_val = next(iter(item.values()), "")
                    lang_code = self._to_iso_lang(str(first_val))
                    languages.append({"lang_code": lang_code, "language": "", "description": ""})
            elif isinstance(item, str) and item.strip():
                lang_code = self._to_iso_lang(item)
                languages.append({"lang_code": lang_code, "language": "", "description": ""})

        return languages

    # -- creators ------------------------------------------------------

    def _normalize_creators(self, value: object) -> list[dict[str, Any]]:
        creators: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "creator_name" in item:
                    creator = {
                        "creator_name": item["creator_name"],
                        "creator_name_type": item.get("creator_name_type", "Organizational"),
                        "given_name": item.get("given_name", ""),
                        "family_name": item.get("family_name", ""),
                        "email": item.get("email", ""),
                        "genre": item.get("genre", ""),
                        "type": item.get("type", "Organization"),
                        "contributor_type": item.get("contributor_type", ""),
                        "name_identifiers": item.get("name_identifiers", []),
                        "affiliations": item.get("affiliations", []),
                    }
                    creators.append(creator)
                elif "name" in item:
                    creators.append(
                        {
                            "creator_name": item.get("name"),
                            "creator_name_type": item.get(
                                "creator_name_type",
                                item.get("name_type", "Organizational"),
                            ),
                            "given_name": item.get("given_name", ""),
                            "family_name": item.get("family_name", ""),
                            "email": item.get("email", ""),
                            "genre": item.get("genre", ""),
                            "type": item.get("type", "Organization"),
                            "contributor_type": item.get("contributor_type", ""),
                            "name_identifiers": item.get("name_identifiers", []),
                            "affiliations": item.get("affiliations", []),
                        }
                    )
                else:
                    first_val = next(iter(item.values()), "")
                    if first_val:
                        creators.append(
                            {
                                "creator_name": str(first_val),
                                "creator_name_type": "Organizational",
                                "given_name": "",
                                "family_name": "",
                                "email": "",
                                "genre": "",
                                "type": "Organization",
                                "contributor_type": "",
                                "name_identifiers": [],
                                "affiliations": [],
                            }
                        )
            elif isinstance(item, str) and item.strip():
                creators.append(
                    {
                        "creator_name": item.strip(),
                        "creator_name_type": "Organizational",
                        "given_name": "",
                        "family_name": "",
                        "email": "",
                        "genre": "",
                        "type": "Organization",
                        "contributor_type": "",
                        "name_identifiers": [],
                        "affiliations": [],
                    }
                )

        return creators

    # -- publishers ----------------------------------------------------

    def _normalize_publishers(self, value: object) -> list[dict[str, Any]]:
        publishers: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "publisher_name" in item:
                    publishers.append(item)
                elif "name" in item:
                    publishers.append(
                        {
                            "publisher_name": item.get("name"),
                            "publisher_identifier": item.get("publisher_identifier", ""),
                            "publisher_identifier_scheme": item.get(
                                "publisher_identifier_scheme", ""
                            ),
                            "publisher_scheme_uri": item.get("publisher_scheme_uri", ""),
                        }
                    )
                else:
                    first_val = next(iter(item.values()), "")
                    if first_val:
                        publishers.append(
                            {
                                "publisher_name": str(first_val),
                                "publisher_identifier": "publisher_identifier",
                                "publisher_identifier_scheme": "publisher_identifier_scheme",
                                "publisher_scheme_uri": "publisher_scheme_uri",
                            }
                        )
            elif isinstance(item, str) and item.strip():
                publishers.append(
                    {
                        "publisher_name": item.strip(),
                        "publisher_identifier": "publisher_identifier",
                        "publisher_identifier_scheme": "publisher_identifier_scheme",
                        "publisher_scheme_uri": "publisher_scheme_uri",
                    }
                )

        return publishers

    # -- subjects ------------------------------------------------------

    def _normalize_subjects(self, value: object) -> list[dict[str, Any]]:
        subjects: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "subject_name" in item:
                    subjects.append(item)
                elif "name" in item:
                    subjects.append(
                        {
                            "subject_name": item.get("name"),
                            "subject_scheme": item.get("subject_scheme", ""),
                            "scheme_uri": item.get("scheme_uri", ""),
                            "value_uri": item.get("value_uri", ""),
                            "classification_code": item.get("classification_code", ""),
                        }
                    )
                else:
                    first_val = next(iter(item.values()), "")
                    if first_val:
                        subjects.append(
                            {
                                "subject_name": str(first_val),
                                "subject_scheme": "",
                                "scheme_uri": "",
                                "value_uri": "",
                                "classification_code": "",
                            }
                        )
            elif isinstance(item, str) and item.strip():
                subjects.append(
                    {
                        "subject_name": item.strip(),
                        "subject_scheme": "",
                        "scheme_uri": "",
                        "value_uri": "",
                        "classification_code": "",
                    }
                )

        return subjects

    # -- dates ---------------------------------------------------------

    def _normalize_dates(self, value: object) -> list[dict[str, Any]]:
        dates: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for i, item in enumerate(items):
            if isinstance(item, dict):
                date_val = item.get("date", "")
                if not date_val:
                    first_val = next(iter(item.values()), "")
                    date_val = str(first_val) if first_val else ""

                if date_val:
                    date_info = (
                        item.get("date_information", "")
                        or item.get("context", "")
                        or item.get("description", "")
                    )
                    dates.append(
                        {
                            "date": str(date_val),
                            "date_type": item.get("date_type", "Issued" if i == 0 else "Updated"),
                            "date_information": str(date_info) if date_info else "",
                        }
                    )
            elif isinstance(item, str) and item.strip():
                date_type = "Issued" if i == 0 else "Updated"
                dates.append(
                    {
                        "date": item.strip(),
                        "date_type": date_type,
                        "date_information": "",
                    }
                )

        return dates

    # -- temporal_events -----------------------------------------------

    def _normalize_temporal_events(self, value: object) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "start_date" in item or "description" in item:
                    events.append(
                        {
                            "start_date": item.get("start_date", ""),
                            "frequency_number": item.get("frequency_number", ""),
                            "frequency_type": item.get("frequency_type", ""),
                            "description": item.get("description", ""),
                        }
                    )
            elif isinstance(item, str) and item.strip():
                freq = self._FREQ_MAP.get(item.strip().lower(), "")
                events.append(
                    {
                        "start_date": "",
                        "frequency_number": "",
                        "frequency_type": freq,
                        "description": item.strip() if not freq else "",
                    }
                )

        return events

    # -- geo_locations -------------------------------------------------

    def _normalize_geo_locations(self, value: object) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "geo_location_place" in item or "geo_description" in item:
                    locations.append(
                        {
                            "geo_location_place": item.get("geo_location_place", ""),
                            "geo_location_point": item.get("geo_location_point", ""),
                            "geo_location_box": item.get("geo_location_box", ""),
                            "geo_location_polygon": item.get("geo_location_polygon", ""),
                            "geo_description": item.get("geo_description", ""),
                            "coverage": item.get("coverage", ""),
                        }
                    )
                else:
                    first_val = next(iter(item.values()), "")
                    if first_val:
                        locations.append(
                            {
                                "geo_location_place": str(first_val),
                                "geo_location_point": "",
                                "geo_location_box": "",
                                "geo_location_polygon": "",
                                "geo_description": "",
                                "coverage": "",
                            }
                        )
            elif isinstance(item, str) and item.strip():
                locations.append(
                    {
                        "geo_location_place": item.strip(),
                        "geo_location_point": "",
                        "geo_location_box": "",
                        "geo_location_polygon": "",
                        "geo_description": "",
                        "coverage": "",
                    }
                )

        return locations

    # -- media_files ---------------------------------------------------
    # NOTE: "Collections" with capital C is intentional (matches merger.py:675)

    def _normalize_media_files(self, value: object) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                raw_format = item.get("format", "")
                files.append(
                    {
                        "sizes": item.get("sizes", []),
                        "physical_carrier": item.get("physical_carrier", ""),
                        "format": (
                            self._iana_normalizer.normalize(raw_format)
                            if isinstance(raw_format, str)
                            else raw_format
                        ),
                        "variable_measured": item.get("variable_measured", ""),
                        "checksum": item.get("checksum", ""),
                        "data_quality": item.get("data_quality", ""),
                        "measurement_technique": item.get("measurement_technique", ""),
                        "provenance": item.get("provenance", ""),
                        "file_uri": item.get("file_uri", ""),
                        "temporal_resolution": item.get("temporal_resolution", ""),
                        "Collections": item.get("Collections", []),
                    }
                )

        return files

    # -- resource ------------------------------------------------------

    def _normalize_resource(self, value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            resource_type = value.get("resource_type", "")
            if resource_type.lower() not in self.VALID_RESOURCE_TYPES:
                resource_type = "Dataset" if not resource_type.startswith("http") else ""

            return {
                "identifier": value.get("identifier", ""),
                "identifier_type": value.get("identifier_type", ""),
                "editor": value.get("editor", ""),
                "maintainer": value.get("maintainer", ""),
                "contact": value.get("contact", ""),
                "producer": value.get("producer", ""),
                "publication_year": value.get("publication_year", ""),
                "resource_type": resource_type,
                "resource_type_general": value.get("resource_type_general", ""),
                "version": value.get("version", ""),
                "thumbnail": value.get("thumbnail", ""),
                "language": value.get("language", ""),
            }
        elif isinstance(value, str):
            resource_type = value if value.lower() in self.VALID_RESOURCE_TYPES else ""
            return {
                "identifier": "",
                "identifier_type": "",
                "editor": "",
                "maintainer": "",
                "contact": "",
                "producer": "",
                "publication_year": "",
                "resource_type": resource_type,
                "resource_type_general": "",
                "version": "",
                "thumbnail": "",
                "language": "",
            }
        return {}

    # -- rights --------------------------------------------------------

    def _normalize_rights(self, value: object) -> list[dict[str, Any]]:
        rights: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                rights.append(
                    {
                        "rights": item.get("rights", item.get("license", "")),
                        "rights_uri": item.get("rights_uri", item.get("license_url", "")),
                        "rights_identifier": item.get("rights_identifier", ""),
                        "rights_identifier_scheme": item.get("rights_identifier_scheme", "SPDX"),
                        "scheme_uri": item.get("scheme_uri", ""),
                        "rights_condition": item.get("rights_condition", ""),
                        "rights_holder": item.get("rights_holder", ""),
                    }
                )
            elif isinstance(item, str) and item.strip():
                rights.append(
                    {
                        "rights": item.strip(),
                        "rights_uri": "",
                        "rights_identifier": "",
                        "rights_identifier_scheme": "",
                        "scheme_uri": "",
                        "rights_condition": "",
                        "rights_holder": "",
                    }
                )

        return rights

    # -- funding_references --------------------------------------------

    def _normalize_funding_references(self, value: object) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                refs.append(
                    {
                        "funder_name": item.get("funder_name", item.get("funder", "")),
                        "funding_stream": item.get("funding_stream", ""),
                        "award_number": item.get("award_number", item.get("grant_number", "")),
                        "award_uri": item.get("award_uri", ""),
                        "award_title": item.get("award_title", item.get("project_title", "")),
                        "funder_identifiers": item.get("funder_identifiers", []),
                    }
                )
            elif isinstance(item, str) and item.strip():
                refs.append(
                    {
                        "funder_name": item.strip(),
                        "funding_stream": "",
                        "award_number": "",
                        "award_uri": "",
                        "award_title": "",
                        "funder_identifiers": [],
                    }
                )

        return refs

    # -- related_identifiers -------------------------------------------

    def _normalize_related_identifiers(self, value: object) -> list[dict[str, Any]]:
        ids: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                ids.append(
                    {
                        "related_identifier": item.get(
                            "related_identifier", item.get("identifier", "")
                        ),
                        "related_identifier_type": item.get("related_identifier_type", "URL"),
                        "relation_type": item.get("relation_type", "IsPartOf"),
                        "related_metadata_scheme": item.get("related_metadata_scheme", ""),
                        "scheme_uri": item.get("scheme_uri", ""),
                        "scheme_type": item.get("scheme_type", ""),
                        "resource_type_general": item.get("resource_type_general", "Dataset"),
                        "contact": item.get("contact", ""),
                    }
                )
            elif isinstance(item, str) and item.strip():
                ids.append(
                    {
                        "related_identifier": item.strip(),
                        "related_identifier_type": "URL",
                        "relation_type": "References",
                        "related_metadata_scheme": "",
                        "scheme_uri": "",
                        "scheme_type": "",
                        "resource_type_general": "",
                        "contact": "",
                    }
                )

        return ids

    # -- alternate_identifiers -----------------------------------------

    def _normalize_alternate_identifiers(self, value: object) -> list[dict[str, Any]]:
        ids: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                ids.append(
                    {
                        "alternate_name": item.get("alternate_name", item.get("name", "")),
                        "alternate_identifier": item.get(
                            "alternate_identifier", item.get("identifier", "")
                        ),
                        "alternate_identifier_type": item.get("alternate_identifier_type", "Local"),
                    }
                )
            elif isinstance(item, str) and item.strip():
                ids.append(
                    {
                        "alternate_name": item.strip(),
                        "alternate_identifier": "",
                        "alternate_identifier_type": "",
                    }
                )

        return ids

    # -- audiences -----------------------------------------------------

    def _normalize_audiences(self, value: object) -> list[dict[str, Any]]:
        audiences: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                audiences.append(
                    {
                        "audience": item.get("audience", ""),
                        "mediator": item.get("mediator", ""),
                        "education_level": item.get("education_level", ""),
                        "instructional_method": item.get("instructional_method", ""),
                    }
                )
            elif isinstance(item, str) and item.strip():
                audiences.append(
                    {
                        "audience": item.strip(),
                        "mediator": "",
                        "education_level": "",
                        "instructional_method": "",
                    }
                )

        return audiences

    # -- categories ----------------------------------------------------

    def _normalize_categories(self, value: object) -> list[dict[str, Any]]:
        cats: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                cats.append(
                    {
                        "name": item.get("name", item.get("category", "")),
                        "sub_category": item.get("sub_category", item.get("subcategory", "")),
                    }
                )
            elif isinstance(item, str) and item.strip():
                cats.append({"name": item.strip(), "sub_category": ""})

        return cats

    # -- citations -----------------------------------------------------

    def _normalize_citations(self, value: object) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                citations.append(
                    {
                        "title": item.get("title", ""),
                        "volume": item.get("volume", ""),
                        "issue": item.get("issue", ""),
                        "start_page": item.get("start_page", ""),
                        "end_page": item.get("end_page", ""),
                        "edition": item.get("edition", ""),
                        "conference_place": item.get("conference_place", ""),
                        "conference_date": item.get("conference_date", ""),
                    }
                )
            elif isinstance(item, str) and item.strip():
                citations.append(
                    {
                        "title": item.strip(),
                        "volume": "",
                        "issue": "",
                        "start_page": "",
                        "end_page": "",
                        "edition": "",
                        "conference_place": "",
                        "conference_date": "",
                    }
                )

        return citations


# ------------------------------------------------------------------
# Build dispatch table after class definition
# ------------------------------------------------------------------
DataCiteSchema46._NORMALIZER_DISPATCH = {
    "titles": "_normalize_titles",
    "descriptions": "_normalize_descriptions",
    "languages": "_normalize_languages",
    "creators": "_normalize_creators",
    "publishers": "_normalize_publishers",
    "subjects": "_normalize_subjects",
    "dates": "_normalize_dates",
    "temporal_events": "_normalize_temporal_events",
    "geo_locations": "_normalize_geo_locations",
    "media_files": "_normalize_media_files",
    "resource": "_normalize_resource",
    "rights": "_normalize_rights",
    "funding_references": "_normalize_funding_references",
    "related_identifiers": "_normalize_related_identifiers",
    "alternate_identifiers": "_normalize_alternate_identifiers",
    "audiences": "_normalize_audiences",
    "categories": "_normalize_categories",
    "citations": "_normalize_citations",
}
