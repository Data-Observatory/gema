"""Merger for combining agent outputs into DataCite format."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MetadataMerger:
    """Merges outputs from multiple agents into final DataCite metadata."""

    REQUIRED_FIELDS = ["titles"]

    def __init__(self):
        self.warnings: list[str] = []

    def merge(
        self,
        agent_outputs: dict[str, dict[str, Any]],
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.warnings = []
        result: dict[str, Any] = {}

        for agent_id, output in agent_outputs.items():
            if output is None:
                logger.warning(f"Agent '{agent_id}' produced no output")
                continue

            normalized = self._normalize_output(output)
            result = self._deep_merge(result, normalized)

        if input_data:
            result = self._fill_from_input(result, input_data)

        missing = self._validate_required_fields(result)
        for field in missing:
            self.warnings.append(f"Missing required field: {field}")

        result = self._clean_empty_fields(result)
        wrapped = {"attributes": result}
        return wrapped

    def _fill_from_input(self, result: dict, input_data: dict) -> dict:
        if "resource" not in result:
            result["resource"] = {}

        if input_data.get("url") and not result["resource"].get("identifier"):
            result["resource"]["identifier"] = input_data["url"]
            result["resource"]["identifier_type"] = "URL"

        if input_data.get("title") and "titles" not in result:
            result["titles"] = [
                {"name": input_data["title"], "title_type": "MainTitle"}
            ]

        if input_data.get("description") and "descriptions" not in result:
            result["descriptions"] = [
                {
                    "description": input_data["description"],
                    "description_type": "Abstract",
                }
            ]

        if input_data.get("publisher"):
            if "publishers" not in result:
                result["publishers"] = [{"publisher_name": input_data["publisher"]}]
            if "creators" not in result:
                result["creators"] = [
                    {
                        "creator_name": input_data["publisher"],
                        "creator_name_type": "Organizational",
                        "type": "Organization",
                    }
                ]

        if input_data.get("frequency"):
            freq_map = {
                "mensual": "monthly",
                "monthly": "monthly",
                "diario": "daily",
                "daily": "daily",
                "semanal": "weekly",
                "weekly": "weekly",
                "anual": "yearly",
                "yearly": "yearly",
            }
            freq = freq_map.get(
                input_data["frequency"].lower(), input_data["frequency"]
            )
            if "temporal_events" not in result:
                result["temporal_events"] = []
            has_freq = any(
                e.get("frequency_type") for e in result.get("temporal_events", [])
            )
            if not has_freq:
                result["temporal_events"].append(
                    {
                        "frequency_type": freq,
                        "description": f"Update frequency: {input_data['frequency']}",
                    }
                )

        return result

    def _normalize_output(self, output):
        normalized = {}
        
        # Manejar listas
        if isinstance(output, list):
            if len(output) > 0 and isinstance(output[0], dict):
                output = output[0]
            else:
                return normalized
        
        if not isinstance(output, dict):
            return normalized
        
        # ✅ NUEVO: Mover campos sueltos a "resource"
        resource_fields = [
            "identifier", "identifier_type", "editor", "maintainer", 
            "contact", "producer", "publication_year", "resource_type",
            "resource_type_general", "version", "thumbnail", "language"
        ]
        
        resource_data = {}
        for field in resource_fields:
            if field in output:
                resource_data[field] = output.pop(field)
        
        if resource_data:
            if "resource" in output:
                output["resource"].update(resource_data)
            else:
                output["resource"] = resource_data
        
        # Procesar campos
        for key, value in output.items():
            if value is None:
             continue
            normalized[key] = self._normalize_field(key, value)
        
        return normalized

    def _normalize_field(self, field_name: str, value: Any) -> Any:
        """Normalize a single field to match template structure."""

        if field_name == "titles":
            return self._normalize_titles(value)
        elif field_name == "descriptions":
            return self._normalize_descriptions(value)
        elif field_name == "languages":
            return self._normalize_languages(value)
        elif field_name == "creators":
            return self._normalize_creators(value)
        elif field_name == "publishers":
            return self._normalize_publishers(value)
        elif field_name == "subjects":
            return self._normalize_subjects(value)
        elif field_name == "dates":
            return self._normalize_dates(value)
        elif field_name == "temporal_events":
            return self._normalize_temporal_events(value)
        elif field_name == "geo_locations":
            return self._normalize_geo_locations(value)
        elif field_name == "media_files":
            return self._normalize_media_files(value)
        elif field_name == "resource":
            return self._normalize_resource(value)
        elif field_name == "rights":
            return self._normalize_rights(value)
        elif field_name == "funding_references":
            return self._normalize_funding_references(value)
        elif field_name == "related_identifiers":
            return self._normalize_related_identifiers(value)
        elif field_name == "alternate_identifiers":
            return self._normalize_alternate_identifiers(value)
        elif field_name == "audiences":
            return self._normalize_audiences(value)
        elif field_name == "categories":
            return self._normalize_categories(value)
        elif field_name == "citations":
            return self._normalize_citations(value)
        else:
            return value

    def _normalize_titles(self, value: Any) -> list[dict]:
        titles = []
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

    def _normalize_descriptions(self, value: Any) -> list[dict]:
        descriptions = []
        items = value if isinstance(value, list) else [value]

        for i, item in enumerate(items):
            if isinstance(item, dict):
                if "description" in item:
                    descriptions.append(item)
                elif "text" in item:
                    descriptions.append(
                        {
                            "description": item.get("text"),
                            "description_type": item.get(
                                "description_type", "Abstract"
                            ),
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

    LANG_CODE_MAP = {
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

    def _to_iso_lang(self, value: str) -> str:
        v = value.strip().lower()
        if v in self.LANG_CODE_MAP:
            return self.LANG_CODE_MAP[v]
        if len(v) == 2:
            return v
        return value

    def _normalize_languages(self, value: Any) -> list[dict]:
        languages = []
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
                    languages.append(
                        {"lang_code": lang_code, "language": "", "description": ""}
                    )
            elif isinstance(item, str) and item.strip():
                lang_code = self._to_iso_lang(item)
                languages.append(
                    {"lang_code": lang_code, "language": "", "description": ""}
                )

        return languages

    def _normalize_creators(self, value: Any) -> list[dict]:
        creators = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "creator_name" in item:
                    creators.append(item)
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

    def _normalize_publishers(self, value: Any) -> list[dict]:
        publishers = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "publisher_name" in item:
                    publishers.append(item)
                elif "name" in item:
                    publishers.append(
                        {
                            "publisher_name": item.get("name"),
                            "publisher_identifier": item.get(
                                "publisher_identifier", ""
                            ),
                            "publisher_identifier_scheme": item.get(
                                "publisher_identifier_scheme", ""
                            ),
                            "publisher_scheme_uri": item.get(
                                "publisher_scheme_uri", ""
                            ),
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

    def _normalize_subjects(self, value: Any) -> list[dict]:
        subjects = []
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

    def _normalize_dates(self, value: Any) -> list[dict]:
        dates = []
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
                            "date_type": item.get(
                                "date_type", "Issued" if i == 0 else "Updated"
                            ),
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

    def _normalize_temporal_events(self, value: Any) -> list[dict]:
        events = []
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
                freq_map = {
                    "mensual": "monthly",
                    "monthly": "monthly",
                    "diario": "daily",
                    "daily": "daily",
                    "semanal": "weekly",
                    "weekly": "weekly",
                    "anual": "yearly",
                    "yearly": "yearly",
                }
                freq = freq_map.get(item.strip().lower(), "")
                events.append(
                    {
                        "start_date": "",
                        "frequency_number": "",
                        "frequency_type": freq,
                        "description": item.strip() if not freq else "",
                    }
                )

        return events

    def _normalize_geo_locations(self, value: Any) -> list[dict]:
        locations = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                if "geo_location_place" in item or "geo_description" in item:
                    locations.append(
                        {
                            "geo_location_place": item.get("geo_location_place", ""),
                            "geo_location_point": item.get("geo_location_point", ""),
                            "geo_location_box": item.get("geo_location_box", ""),
                            "geo_location_polygon": item.get(
                                "geo_location_polygon", ""
                            ),
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

    def _normalize_media_files(self, value: Any) -> list[dict]:
        files = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                files.append(
                    {
                        "sizes": item.get("sizes", []),
                        "physical_carrier": item.get("physical_carrier", ""),
                        "format": item.get("format", ""),
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

    VALID_RESOURCE_TYPES = {
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

    def _normalize_resource(self, value: Any) -> dict:
        if isinstance(value, dict):
            resource_type = value.get("resource_type", "")
            if resource_type.lower() not in self.VALID_RESOURCE_TYPES:
                resource_type = (
                    "Dataset" if not resource_type.startswith("http") else ""
                )

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

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = base.copy()

        for key, value in override.items():
            if value is None:
                continue

            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = self._deep_merge(result[key], value)
                elif isinstance(result[key], list) and isinstance(value, list):
                    result[key] = result[key] + value
                else:
                    result[key] = value
            else:
                result[key] = value

        return result

    def _normalize_rights(self, value: Any) -> list[dict]:
        rights = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                rights.append(
                    {
                        "rights": item.get("rights", item.get("license", "")),
                        "rights_uri": item.get(
                            "rights_uri", item.get("license_url", "")
                        ),
                        "rights_identifier": item.get("rights_identifier", ""),
                        "rights_identifier_scheme": item.get(
                            "rights_identifier_scheme", "SPDX"
                        ),
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

    def _normalize_funding_references(self, value: Any) -> list[dict]:
        refs = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                refs.append(
                    {
                        "funder_name": item.get("funder_name", item.get("funder", "")),
                        "funding_stream": item.get("funding_stream", ""),
                        "award_number": item.get(
                            "award_number", item.get("grant_number", "")
                        ),
                        "award_uri": item.get("award_uri", ""),
                        "award_title": item.get(
                            "award_title", item.get("project_title", "")
                        ),
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

    def _normalize_related_identifiers(self, value: Any) -> list[dict]:
        ids = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                ids.append(
                    {
                        "related_identifier": item.get(
                            "related_identifier", item.get("identifier", "")
                        ),
                        "related_identifier_type": item.get(
                            "related_identifier_type", "URL"
                        ),
                        "relation_type": item.get("relation_type", "IsPartOf"),
                        "related_metadata_scheme": item.get(
                            "related_metadata_scheme", ""
                        ),
                        "scheme_uri": item.get("scheme_uri", ""),
                        "scheme_type": item.get("scheme_type", ""),
                        "resource_type_general": item.get(
                            "resource_type_general", "Dataset"
                        ),
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

    def _normalize_alternate_identifiers(self, value: Any) -> list[dict]:
        ids = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                ids.append(
                    {
                        "alternate_name": item.get(
                            "alternate_name", item.get("name", "")
                        ),
                        "alternate_identifier": item.get(
                            "alternate_identifier", item.get("identifier", "")
                        ),
                        "alternate_identifier_type": item.get(
                            "alternate_identifier_type", "Local"
                        ),
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

    def _normalize_audiences(self, value: Any) -> list[dict]:
        audiences = []
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

    def _normalize_categories(self, value: Any) -> list[dict]:
        cats = []
        items = value if isinstance(value, list) else [value]

        for item in items:
            if isinstance(item, dict):
                cats.append(
                    {
                        "name": item.get("name", item.get("category", "")),
                        "sub_category": item.get(
                            "sub_category", item.get("subcategory", "")
                        ),
                    }
                )
            elif isinstance(item, str) and item.strip():
                cats.append({"name": item.strip(), "sub_category": ""})

        return cats

    def _normalize_citations(self, value: Any) -> list[dict]:
        citations = []
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

    def _clean_empty_fields(self, data: dict) -> dict:
        cleaned = {}
        for key, value in data.items():
            if isinstance(value, list):
                if len(value) > 0:
                    cleaned_list = []
                    for item in value:
                        if isinstance(item, dict):
                            clean_item = self._clean_dict(item)
                            if clean_item:
                                cleaned_list.append(clean_item)
                        elif item not in (None, "", [], {}):
                            cleaned_list.append(item)
                    if cleaned_list:
                        cleaned[key] = cleaned_list
            elif isinstance(value, dict):
                clean_dict = self._clean_dict(value)
                if clean_dict:
                    cleaned[key] = clean_dict
            elif value not in (None, ""):
                cleaned[key] = value
        return cleaned

    def _clean_dict(self, d: dict) -> dict:
        cleaned = {}
        for k, v in d.items():
            if isinstance(v, dict):
                clean_v = self._clean_dict(v)
                if clean_v:
                    cleaned[k] = clean_v
            elif isinstance(v, list):
                if len(v) > 0:
                    cleaned_list = []
                    for item in v:
                        if isinstance(item, dict):
                            clean_item = self._clean_dict(item)
                            if clean_item:
                                cleaned_list.append(clean_item)
                        elif item not in (None, "", [], {}):
                            cleaned_list.append(item)
                    if cleaned_list:
                        cleaned[k] = cleaned_list
            elif v not in (None, ""):
                cleaned[k] = v
        return cleaned

    def _validate_required_fields(self, result: dict[str, Any]) -> list[str]:
        missing = []

        for field in self.REQUIRED_FIELDS:
            if field not in result or result[field] is None:
                missing.append(field)
            elif isinstance(result[field], list) and len(result[field]) == 0:
                missing.append(field)

        return missing

    def get_warnings(self) -> list[str]:
        return self.warnings.copy()
