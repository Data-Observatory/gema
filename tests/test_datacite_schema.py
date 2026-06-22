"""Tests for DataCite 4.6 Schema implementation."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from metadata_enricher.schemas import DataCiteSchema46, get_registry
from metadata_enricher.schemas.base import SchemaRegistry
from metadata_enricher.types import AgentResult, MetadataDocument


class TestSchemaProperties:
    """Schema identity and configuration."""

    def test_name(self) -> None:
        schema = DataCiteSchema46()
        assert schema.name == "datacite-4.6"

    def test_version(self) -> None:
        schema = DataCiteSchema46()
        assert schema.version == "4.6"

    def test_output_model(self) -> None:
        schema = DataCiteSchema46()
        assert issubclass(schema.output_model, BaseModel)

    def test_get_field_order(self) -> None:
        schema = DataCiteSchema46()
        field_order = schema.get_field_order()
        assert isinstance(field_order, list)
        assert "titles" in field_order
        assert "resource" in field_order
        assert "creators" in field_order
        assert field_order[0] == "resource"
        assert field_order[-1] == "titles"
        assert len(field_order) == 18

    def test_get_required_fields(self) -> None:
        schema = DataCiteSchema46()
        assert schema.get_required_fields() == ["titles"]

    def test_valid_resource_types(self) -> None:
        assert "dataset" in DataCiteSchema46.VALID_RESOURCE_TYPES
        assert "software" in DataCiteSchema46.VALID_RESOURCE_TYPES
        assert "collection" in DataCiteSchema46.VALID_RESOURCE_TYPES
        assert "other" in DataCiteSchema46.VALID_RESOURCE_TYPES
        assert "invalid_type" not in DataCiteSchema46.VALID_RESOURCE_TYPES


class TestNormalizeTitles:
    """Title normalization."""

    def test_dict_with_name_passes_through(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles(
            [{"name": "A Title", "title_type": "MainTitle", "language": "es"}]
        )
        assert result == [{"name": "A Title", "title_type": "MainTitle", "language": "es"}]

    def test_dict_with_title_key_renamed_to_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles([{"title": "My Title"}])
        assert result == [{"name": "My Title", "title_type": "MainTitle", "language": ""}]

    def test_dict_with_title_key_alternative_title(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles(
            [
                {"name": "Main"},
                {"title": "Second", "title_type": "AlternativeTitle"},
            ]
        )
        assert result[0] == {"name": "Main"}
        assert result[1]["name"] == "Second"
        assert result[1]["title_type"] == "AlternativeTitle"

    def test_dict_without_name_or_title_uses_first_value(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles([{"other": "Fallback Title"}])
        assert result == [{"name": "Fallback Title", "title_type": "MainTitle", "language": ""}]

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles("Single Title")
        assert result == [{"name": "Single Title", "title_type": "MainTitle", "language": ""}]

    def test_multiple_strings(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles(["First Title", "Second Title"])
        assert len(result) == 2
        assert result[0]["title_type"] == "MainTitle"
        assert result[1]["title_type"] == "AlternativeTitle"

    def test_empty_string_skipped(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles(["  ", ""])
        assert result == []

    def test_non_list_wrapped(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_titles({"title": "Single dict"})
        assert len(result) == 1
        assert result[0]["name"] == "Single dict"


class TestNormalizeDescriptions:
    """Description normalization."""

    def test_dict_with_description_passes_through(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_descriptions(
            [{"description": "A description", "description_type": "Abstract"}]
        )
        assert result == [{"description": "A description", "description_type": "Abstract"}]

    def test_dict_with_text_key_renamed(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_descriptions([{"text": "Long text"}])
        assert result == [
            {"description": "Long text", "description_type": "Abstract", "language": ""}
        ]

    def test_dict_without_description_or_text(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_descriptions([{"unknown": "fallback"}])
        assert result == [
            {"description": "fallback", "description_type": "Abstract", "language": ""}
        ]

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_descriptions("A description string")
        assert result == [
            {"description": "A description string", "description_type": "Abstract", "language": ""}
        ]

    def test_mixed_list(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_descriptions(
            [
                {"description": "Explicit desc"},
                "Plain string",
                {"text": "Using text key"},
            ]
        )
        assert len(result) == 3
        assert result[0]["description"] == "Explicit desc"
        assert result[1]["description"] == "Plain string"
        assert result[2]["description"] == "Using text key"


class TestNormalizeLanguages:
    """Language normalization with ISO code mapping."""

    def test_dict_with_lang_code(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages(
            [{"lang_code": "es", "language": "Spanish", "description": "Primary language"}]
        )
        assert result[0]["lang_code"] == "es"
        assert result[0]["language"] == "Spanish"

    def test_dict_with_code_key(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages([{"code": "en"}])
        assert result[0]["lang_code"] == "en"

    def test_spanish_word_to_iso(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages([{"lang_code": "español"}])
        assert result[0]["lang_code"] == "es"

    def test_english_word_to_iso(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages([{"lang_code": "english"}])
        assert result[0]["lang_code"] == "en"

    def test_already_iso_code_passes_through(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages([{"lang_code": "fr"}])
        assert result[0]["lang_code"] == "fr"

    def test_unknown_language_kept(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages([{"lang_code": "valyrian"}])
        assert result[0]["lang_code"] == "valyrian"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages("spanish")
        assert result[0]["lang_code"] == "es"

    def test_dict_without_lang_code_or_code(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_languages([{"language": "German"}])
        assert result[0]["lang_code"] == "de"


class TestNormalizeCreators:
    """Creator normalization."""

    def test_dict_with_creator_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_creators([{"creator_name": "Ministry of Health"}])
        assert result[0]["creator_name"] == "Ministry of Health"
        assert result[0]["creator_name_type"] == "Organizational"

    def test_dict_with_name_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_creators([{"name": "John Doe", "name_type": "Personal"}])
        assert result[0]["creator_name"] == "John Doe"
        assert result[0]["creator_name_type"] == "Personal"

    def test_dict_without_creator_name_or_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_creators([{"unknown_key": "Fallback Org"}])
        assert result[0]["creator_name"] == "Fallback Org"
        assert result[0]["creator_name_type"] == "Organizational"

    def test_with_identifiers_and_affiliations(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_creators(
            [
                {
                    "creator_name": "UChile",
                    "name_identifiers": [
                        {"name_identifier": "ror.org/01abc", "name_identifier_scheme": "ROR"}
                    ],
                    "affiliations": [{"affiliation": "UChile"}],
                }
            ]
        )
        assert result[0]["name_identifiers"] == [
            {"name_identifier": "ror.org/01abc", "name_identifier_scheme": "ROR"}
        ]
        assert result[0]["affiliations"] == [{"affiliation": "UChile"}]

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_creators("John Doe")
        assert result[0]["creator_name"] == "John Doe"
        assert result[0]["creator_name_type"] == "Organizational"

    def test_full_personal_creator(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_creators(
            [
                {
                    "creator_name_type": "Personal",
                    "creator_name": "Jane Smith",
                    "given_name": "Jane",
                    "family_name": "Smith",
                    "email": "jane@example.com",
                }
            ]
        )
        assert result[0]["given_name"] == "Jane"
        assert result[0]["family_name"] == "Smith"
        assert result[0]["email"] == "jane@example.com"


class TestNormalizePublishers:
    """Publisher normalization."""

    def test_dict_with_publisher_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_publishers(
            [{"publisher_name": "Gobierno de Chile", "publisher_identifier": "ror.org/abc"}]
        )
        assert result == [
            {"publisher_name": "Gobierno de Chile", "publisher_identifier": "ror.org/abc"}
        ]

    def test_dict_with_name_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_publishers([{"name": "Ministry"}])
        assert result[0]["publisher_name"] == "Ministry"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_publishers("Some Publisher")
        assert result[0]["publisher_name"] == "Some Publisher"
        assert result[0]["publisher_identifier"] == "publisher_identifier"

    def test_dict_without_publisher_name_or_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_publishers([{"other": "Fallback Pub"}])
        assert result[0]["publisher_name"] == "Fallback Pub"


class TestNormalizeSubjects:
    """Subject normalization."""

    def test_dict_with_subject_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_subjects([{"subject_name": "Economy", "subject_scheme": "JEL"}])
        assert result == [{"subject_name": "Economy", "subject_scheme": "JEL"}]

    def test_dict_with_name_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_subjects([{"name": "Health", "subject_scheme": "UNESCO"}])
        assert result[0]["subject_name"] == "Health"
        assert result[0]["subject_scheme"] == "UNESCO"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_subjects("Climate Change")
        assert result[0]["subject_name"] == "Climate Change"
        assert result[0]["subject_scheme"] == ""

    def test_dict_without_subject_name_or_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_subjects([{"other": "Fallback"}])
        assert result[0]["subject_name"] == "Fallback"


class TestNormalizeDates:
    """Date normalization."""

    def test_dict_with_date(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_dates([{"date": "2024-01-15", "date_type": "Issued"}])
        assert result[0]["date"] == "2024-01-15"
        assert result[0]["date_type"] == "Issued"

    def test_first_item_defaults_to_issued(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_dates([{"date": "2024-06-01"}])
        assert result[0]["date_type"] == "Issued"

    def test_second_item_defaults_to_updated(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_dates(
            [
                {"date": "2024-01-01"},
                {"date": "2024-06-01"},
            ]
        )
        assert result[0]["date_type"] == "Issued"
        assert result[1]["date_type"] == "Updated"

    def test_date_information_fallback_context(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_dates([{"date": "2024-01-01", "context": "Publication date"}])
        assert result[0]["date_information"] == "Publication date"

    def test_date_information_fallback_description(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_dates([{"date": "2024-01-01", "description": "Desc"}])
        assert result[0]["date_information"] == "Desc"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_dates("2024-01-01")
        assert result[0]["date"] == "2024-01-01"
        assert result[0]["date_type"] == "Issued"

    def test_dict_without_date_uses_first_value(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_dates([{"other": "2024-01-01T00:00:00"}])
        assert result[0]["date"] == "2024-01-01T00:00:00"


class TestNormalizeTemporalEvents:
    """Temporal events normalization."""

    def test_dict_with_start_date(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_temporal_events(
            [
                {
                    "start_date": "2020-01-01",
                    "frequency_type": "monthly",
                    "description": "Monthly updates",
                }
            ]
        )
        assert result[0]["start_date"] == "2020-01-01"
        assert result[0]["frequency_type"] == "monthly"

    def test_dict_with_only_description(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_temporal_events([{"description": "Annual report"}])
        assert result[0]["description"] == "Annual report"

    def test_freq_map_spanish(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_temporal_events("mensual")
        assert result[0]["frequency_type"] == "monthly"
        assert result[0]["description"] == ""

    def test_freq_map_diario(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_temporal_events(
            [{"start_date": "2024-01", "frequency_type": "diario"}]
        )
        assert result[0]["frequency_type"] == "diario"

    def test_string_non_frequency(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_temporal_events("evento especial")
        assert result[0]["frequency_type"] == ""
        assert result[0]["description"] == "evento especial"

    def test_dict_without_start_date_or_description(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_temporal_events([{"frequency_type": "annual"}])
        assert result == []  # no start_date or description → skipped


class TestNormalizeGeolocations:
    """Geo-location normalization."""

    def test_dict_with_geo_location_place(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_geo_locations([{"geo_location_place": "Santiago, Chile"}])
        assert result[0]["geo_location_place"] == "Santiago, Chile"

    def test_dict_with_geo_description(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_geo_locations([{"geo_description": "Metropolitan region"}])
        assert result[0]["geo_description"] == "Metropolitan region"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_geo_locations("Chile")
        assert result[0]["geo_location_place"] == "Chile"

    def test_dict_without_geo_fields(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_geo_locations([{"name": "Chile"}])
        assert result[0]["geo_location_place"] == "Chile"

    def test_full_geometry(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_geo_locations(
            [
                {
                    "geo_location_place": "Valparaíso",
                    "geo_location_point": "-33.0478 -71.6199",
                    "geo_location_box": "-33.1 -71.7 -33.0 -71.5",
                }
            ]
        )
        assert result[0]["geo_location_place"] == "Valparaíso"
        assert result[0]["geo_location_point"] == "-33.0478 -71.6199"
        assert result[0]["geo_location_box"] == "-33.1 -71.7 -33.0 -71.5"


class TestNormalizeMediaFiles:
    """Media files normalization."""

    def test_dict_with_format(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_media_files(
            [{"format": "text/csv", "file_uri": "https://example.com/data.csv"}]
        )
        assert result[0]["format"] == "text/csv"
        assert result[0]["file_uri"] == "https://example.com/data.csv"

    def test_collections_capital_c_preserved(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_media_files([{"Collections": ["geo", "health"]}])
        assert result[0]["Collections"] == ["geo", "health"]

    def test_sizes_preserved(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_media_files([{"sizes": [{"size": "250", "unit": "KB"}]}])
        assert result[0]["sizes"] == [{"size": "250", "unit": "KB"}]

    def test_full_media_file(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_media_files(
            [
                {
                    "format": "application/geo+json",
                    "file_uri": "https://example.com/map.geojson",
                    "provenance": "Government of Chile",
                    "checksum": "abc123",
                    "data_quality": "Official",
                    "measurement_technique": "Survey",
                    "temporal_resolution": "P1M",
                    "variable_measured": "Temperature",
                    "physical_carrier": "digital",
                    "sizes": [{"size": "1.5", "unit": "MB"}],
                    "Collections": ["climate"],
                }
            ]
        )
        assert result[0]["format"] == "application/geo+json"
        assert result[0]["checksum"] == "abc123"
        assert result[0]["Collections"] == ["climate"]

    def test_non_dict_skipped(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_media_files("not a dict")
        assert result == []


class TestNormalizeResource:
    """Resource normalization."""

    def test_dict_with_valid_resource_type(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_resource(
            {
                "identifier": "https://example.com",
                "identifier_type": "URL",
                "resource_type": "dataset",
                "resource_type_general": "Dataset",
                "publication_year": "2024",
            }
        )
        assert result["identifier"] == "https://example.com"
        assert result["identifier_type"] == "URL"
        assert result["resource_type"] == "dataset"
        assert result["publication_year"] == "2024"

    def test_invalid_resource_type_replaced_with_dataset(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_resource({"resource_type": "invalid_type"})
        assert result["resource_type"] == "Dataset"

    def test_url_resource_type_cleared(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_resource({"resource_type": "https://example.com"})
        assert result["resource_type"] == ""

    def test_dict_resource_with_all_fields(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_resource(
            {
                "identifier": "https://doi.org/10.1234/abc",
                "identifier_type": "DOI",
                "editor": "Editor Name",
                "maintainer": "Maintainer Name",
                "contact": "email@example.com",
                "producer": "Producer Name",
                "publication_year": "2024",
                "resource_type": "dataset",
                "resource_type_general": "Dataset",
                "version": "1.0",
                "thumbnail": "https://example.com/thumb.png",
                "language": "es",
            }
        )
        assert result["editor"] == "Editor Name"
        assert result["maintainer"] == "Maintainer Name"
        assert result["version"] == "1.0"

    def test_string_resource_with_valid_type(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_resource("dataset")
        assert result["resource_type"] == "dataset"
        assert result["identifier"] == ""

    def test_string_resource_with_invalid_type(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_resource("bogus")
        assert result["resource_type"] == ""

    def test_non_dict_non_string_returns_empty_dict(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_resource(None)
        assert result == {}


class TestNormalizeRights:
    """Rights normalization."""

    def test_dict_with_rights(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_rights(
            [{"rights": "CC BY 4.0", "rights_uri": "https://creativecommons.org/licenses/by/4.0/"}]
        )
        assert result[0]["rights"] == "CC BY 4.0"
        assert result[0]["rights_uri"] == "https://creativecommons.org/licenses/by/4.0/"

    def test_default_scheme_spdx(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_rights([{"rights": "CC BY 4.0"}])
        assert result[0]["rights_identifier_scheme"] == "SPDX"

    def test_license_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_rights(
            [{"license": "MIT", "license_url": "https://opensource.org/licenses/MIT"}]
        )
        assert result[0]["rights"] == "MIT"
        assert result[0]["rights_uri"] == "https://opensource.org/licenses/MIT"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_rights("CC0 1.0")
        assert result[0]["rights"] == "CC0 1.0"
        assert result[0]["rights_uri"] == ""


class TestNormalizeFundingReferences:
    """Funding references normalization."""

    def test_dict_with_funder_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_funding_references(
            [{"funder_name": "ANID", "award_number": "123"}]
        )
        assert result[0]["funder_name"] == "ANID"
        assert result[0]["award_number"] == "123"

    def test_funder_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_funding_references([{"funder": "Fondecyt"}])
        assert result[0]["funder_name"] == "Fondecyt"

    def test_grant_number_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_funding_references(
            [{"funder_name": "CONICYT", "grant_number": "456"}]
        )
        assert result[0]["award_number"] == "456"

    def test_project_title_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_funding_references(
            [{"funder_name": "ANID", "project_title": "Research Project"}]
        )
        assert result[0]["award_title"] == "Research Project"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_funding_references("NSF")
        assert result[0]["funder_name"] == "NSF"

    def test_with_funder_identifiers(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_funding_references(
            [
                {
                    "funder_name": "ANID",
                    "funder_identifiers": [
                        {"funder_identifier": "ror.org/02abc", "funder_identifier_type": "ROR"}
                    ],
                }
            ]
        )
        assert result[0]["funder_identifiers"] == [
            {"funder_identifier": "ror.org/02abc", "funder_identifier_type": "ROR"}
        ]


class TestNormalizeRelatedIdentifiers:
    """Related identifiers normalization."""

    def test_dict_with_related_identifier(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_related_identifiers(
            [
                {
                    "related_identifier": "https://example.com/related",
                    "relation_type": "IsPartOf",
                }
            ]
        )
        assert result[0]["related_identifier"] == "https://example.com/related"
        assert result[0]["relation_type"] == "IsPartOf"

    def test_default_type_is_url(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_related_identifiers([{"related_identifier": "doi:10.1234/abc"}])
        assert result[0]["related_identifier_type"] == "URL"

    def test_identifier_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_related_identifiers([{"identifier": "https://example.com"}])
        assert result[0]["related_identifier"] == "https://example.com"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_related_identifiers("https://example.com")
        assert result[0]["related_identifier"] == "https://example.com"
        assert result[0]["relation_type"] == "References"


class TestNormalizeAlternateIdentifiers:
    """Alternate identifiers normalization."""

    def test_dict_with_alternate_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_alternate_identifiers(
            [{"alternate_name": "Alt Name", "alternate_identifier": "ID123"}]
        )
        assert result[0]["alternate_name"] == "Alt Name"
        assert result[0]["alternate_identifier"] == "ID123"

    def test_name_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_alternate_identifiers([{"name": "Alt"}])
        assert result[0]["alternate_name"] == "Alt"

    def test_identifier_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_alternate_identifiers([{"identifier": "ID456"}])
        assert result[0]["alternate_identifier"] == "ID456"

    def test_default_type_local(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_alternate_identifiers([{"alternate_name": "Test"}])
        assert result[0]["alternate_identifier_type"] == "Local"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_alternate_identifiers("LocalID")
        assert result[0]["alternate_name"] == "LocalID"


class TestNormalizeAudiences:
    """Audience normalization."""

    def test_dict_with_audience(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_audiences(
            [{"audience": "Researchers", "education_level": "PhD"}]
        )
        assert result[0]["audience"] == "Researchers"
        assert result[0]["education_level"] == "PhD"

    def test_full_audience_dict(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_audiences(
            [
                {
                    "audience": "Policy makers",
                    "mediator": "Government",
                    "education_level": "Professional",
                    "instructional_method": "Workshop",
                }
            ]
        )
        assert result[0]["audience"] == "Policy makers"
        assert result[0]["mediator"] == "Government"
        assert result[0]["education_level"] == "Professional"
        assert result[0]["instructional_method"] == "Workshop"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_audiences("General Public")
        assert result[0]["audience"] == "General Public"


class TestNormalizeCategories:
    """Category normalization."""

    def test_dict_with_name(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_categories(
            [{"name": "Social Sciences", "sub_category": "Economics"}]
        )
        assert result[0]["name"] == "Social Sciences"
        assert result[0]["sub_category"] == "Economics"

    def test_category_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_categories([{"category": "Health"}])
        assert result[0]["name"] == "Health"

    def test_subcategory_alias(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_categories([{"name": "Sciences", "subcategory": "Physics"}])
        assert result[0]["sub_category"] == "Physics"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_categories("Engineering")
        assert result[0]["name"] == "Engineering"
        assert result[0]["sub_category"] == ""


class TestNormalizeCitations:
    """Citation normalization."""

    def test_dict_with_title(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_citations(
            [{"title": "Research Paper", "volume": "10", "issue": "2"}]
        )
        assert result[0]["title"] == "Research Paper"
        assert result[0]["volume"] == "10"
        assert result[0]["issue"] == "2"

    def test_full_citation_dict(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_citations(
            [
                {
                    "title": "Important Study",
                    "volume": "5",
                    "issue": "1",
                    "start_page": "100",
                    "end_page": "120",
                    "edition": "2nd",
                    "conference_place": "Santiago",
                    "conference_date": "2024-03-15",
                }
            ]
        )
        assert result[0]["title"] == "Important Study"
        assert result[0]["start_page"] == "100"
        assert result[0]["conference_place"] == "Santiago"

    def test_string_input(self) -> None:
        schema = DataCiteSchema46()
        result = schema._normalize_citations("Generic Citation")
        assert result[0]["title"] == "Generic Citation"


class TestNormalizeFieldDispatch:
    """Field dispatch via normalize_field."""

    def test_known_field_dispatches(self) -> None:
        schema = DataCiteSchema46()
        result = schema.normalize_field("titles", "Title Value")
        assert isinstance(result, list)
        assert result[0]["name"] == "Title Value"

    def test_unknown_field_passes_through(self) -> None:
        schema = DataCiteSchema46()
        result = schema.normalize_field("custom_field", {"key": "value"})
        assert result == {"key": "value"}

    def test_all_known_fields_dispatched(self) -> None:
        schema = DataCiteSchema46()
        known_fields = [
            "titles",
            "descriptions",
            "languages",
            "creators",
            "publishers",
            "subjects",
            "dates",
            "temporal_events",
            "geo_locations",
            "media_files",
            "resource",
            "rights",
            "funding_references",
            "related_identifiers",
            "alternate_identifiers",
            "audiences",
            "categories",
            "citations",
        ]
        for field in known_fields:
            result = schema.normalize_field(field, [])
            assert result is not None, f"normalize_field({field!r}) returned None"


class TestMergeAgentResults:
    """merge_agent_results integration."""

    def test_merges_multiple_agents(self) -> None:
        schema = DataCiteSchema46()
        results = [
            AgentResult(field_name="titles", value=[{"title": "Test Dataset"}]),
            AgentResult(field_name="creators", value=[{"creator_name": "Org"}]),
            AgentResult(field_name="dates", value=[{"date": "2024-01-01"}]),
        ]
        doc = schema.merge_agent_results(results)

        assert "titles" in doc.fields
        assert doc.fields["titles"][0]["name"] == "Test Dataset"
        assert "creators" in doc.fields
        assert doc.fields["creators"][0]["creator_name"] == "Org"
        assert "dates" in doc.fields
        assert doc.fields["dates"][0]["date"] == "2024-01-01"

    def test_agent_with_error_skipped(self) -> None:
        schema = DataCiteSchema46()
        results = [
            AgentResult(field_name="titles", value=[{"title": "OK"}], error="Something went wrong"),
            AgentResult(field_name="creators", value=[{"creator_name": "Should be there"}]),
        ]
        doc = schema.merge_agent_results(results)
        assert "titles" not in doc.fields  # skipped due to error
        assert "creators" in doc.fields

    def test_agent_with_none_value_skipped(self) -> None:
        schema = DataCiteSchema46()
        results = [
            AgentResult(field_name="titles", value=None),
            AgentResult(field_name="creators", value=[{"creator_name": "Present"}]),
        ]
        doc = schema.merge_agent_results(results)
        assert "titles" not in doc.fields
        assert "creators" in doc.fields

    def test_same_field_multiple_agents_concatenate(self) -> None:
        schema = DataCiteSchema46()
        results = [
            AgentResult(field_name="titles", value=[{"title": "Title A"}]),
            AgentResult(field_name="titles", value=[{"title": "Title B"}]),
        ]
        doc = schema.merge_agent_results(results)
        assert len(doc.fields["titles"]) == 2
        assert doc.fields["titles"][0]["name"] == "Title A"
        assert doc.fields["titles"][1]["name"] == "Title B"

    def test_resource_merged_correctly(self) -> None:
        schema = DataCiteSchema46()
        results = [
            AgentResult(
                field_name="resource",
                value={"identifier": "https://a.com", "resource_type": "dataset"},
            ),
            AgentResult(field_name="resource", value={"publication_year": "2024"}),
        ]
        doc = schema.merge_agent_results(results)
        assert doc.fields["resource"]["identifier"] == "https://a.com"
        assert doc.fields["resource"]["publication_year"] == "2024"
        assert doc.fields["resource"]["resource_type"] == "dataset"

    def test_field_ordering_preserved(self) -> None:
        schema = DataCiteSchema46()
        results = [
            AgentResult(field_name="creators", value=[{"creator_name": "Org"}]),
            AgentResult(field_name="titles", value=[{"title": "T"}]),
            AgentResult(field_name="resource", value={"identifier": "https://x.com"}),
        ]
        doc = schema.merge_agent_results(results)
        field_names = list(doc.fields.keys())
        # resource should come before creators, which should come before titles
        res_idx = field_names.index("resource")
        cr_idx = field_names.index("creators")
        ti_idx = field_names.index("titles")
        assert res_idx < cr_idx < ti_idx

    def test_result_is_metadata_document(self) -> None:
        schema = DataCiteSchema46()
        doc = schema.merge_agent_results(
            [AgentResult(field_name="titles", value=[{"title": "Test"}])]
        )
        assert isinstance(doc, MetadataDocument)

    def test_empty_results_produces_empty_document(self) -> None:
        schema = DataCiteSchema46()
        doc = schema.merge_agent_results([])
        assert doc.fields == {}

    def test_unknown_field_passthrough(self) -> None:
        schema = DataCiteSchema46()
        results = [
            AgentResult(field_name="custom_extension", value={"data": "value"}),
        ]
        doc = schema.merge_agent_results(results)
        assert doc.fields["custom_extension"] == {"data": "value"}


class TestValidateOutput:
    """Output model validation."""

    def test_validates_minimal_output(self) -> None:
        schema = DataCiteSchema46()
        model = schema.validate_output({"titles": [{"name": "Test"}]})
        assert model.titles == [{"name": "Test"}]

    def test_validates_full_output(self) -> None:
        schema = DataCiteSchema46()
        raw = {
            "titles": [{"name": "Dataset", "title_type": "MainTitle"}],
            "creators": [{"creator_name": "Org"}],
            "resource": {"identifier": "https://example.com", "resource_type": "dataset"},
            "dates": [{"date": "2024-01-01", "date_type": "Issued"}],
            "custom_field": "extra",  # extra="allow"
        }
        model = schema.validate_output(raw)
        assert model.titles == raw["titles"]
        assert model.creators == raw["creators"]
        assert model.custom_field == "extra"

    def test_extra_fields_allowed(self) -> None:
        schema = DataCiteSchema46()
        model = schema.validate_output({"titles": [], "extra_thing": 42})
        assert model.extra_thing == 42

    def test_defaults_for_missing_fields(self) -> None:
        schema = DataCiteSchema46()
        model = schema.validate_output({})
        assert model.titles == []
        assert model.creators == []
        assert model.resource == {}
        assert model.media_files == []


class TestRegistryIntegration:
    """Schema registered and retrievable via get_registry."""

    def test_registered_in_registry(self) -> None:
        registry = get_registry()
        schema = registry.get("datacite-4.6")
        assert schema.name == "datacite-4.6"
        assert schema.version == "4.6"

    def test_registry_is_schema_registry_instance(self) -> None:
        registry = get_registry()
        assert isinstance(registry, SchemaRegistry)

    def test_datacite_listed_in_registry(self) -> None:
        registry = get_registry()
        schemas = registry.list_schemas()
        assert "datacite-4.6" in schemas

    def test_registry_schema_methods_work(self) -> None:
        registry = get_registry()
        schema = registry.get("datacite-4.6")
        assert isinstance(schema.get_field_order(), list)
        assert schema.get_required_fields() == ["titles"]
        result = schema.normalize_field("titles", "Hello")
        assert isinstance(result, list)
        assert result[0]["name"] == "Hello"

    def test_registry_schema_protocol(self) -> None:
        from metadata_enricher.schemas.base import Schema

        registry = get_registry()
        schema = registry.get("datacite-4.6")
        assert isinstance(schema, Schema)


class TestLanguageCodeMap:
    """Language code mapping conversion."""

    def test_known_map_entries(self) -> None:
        schema = DataCiteSchema46()
        assert schema.LANG_CODE_MAP["spanish"] == "es"
        assert schema.LANG_CODE_MAP["english"] == "en"
        assert schema.LANG_CODE_MAP["french"] == "fr"
        assert schema.LANG_CODE_MAP["german"] == "de"

    def test_to_iso_lang_mapped(self) -> None:
        schema = DataCiteSchema46()
        assert schema._to_iso_lang("spanish") == "es"
        assert schema._to_iso_lang("ESPAÑOL") == "es"

    def test_to_iso_lang_two_letter_passthrough(self) -> None:
        schema = DataCiteSchema46()
        assert schema._to_iso_lang("es") == "es"
        assert schema._to_iso_lang("en") == "en"
        assert schema._to_iso_lang("pt") == "pt"

    def test_to_iso_lang_unknown_kept(self) -> None:
        schema = DataCiteSchema46()
        assert schema._to_iso_lang("valyrian") == "valyrian"
        assert schema._to_iso_lang("xyz") == "xyz"  # 3 chars, not 2
