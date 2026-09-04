"""Tests for exporters/croissant.py — CDIF MetadataDocument -> MLCommons
Croissant JSON-LD, top-level Dataset fields only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metadata_enricher.exporters.croissant import (
    CROISSANT_CONFORMS_TO,
    CroissantExportResult,
    to_croissant_json,
)
from metadata_enricher.types import MetadataDocument, TokenUsage


def make_document(**fields: object) -> MetadataDocument:
    doc = MetadataDocument()
    for key, value in fields.items():
        doc.set_field(key, value)
    return doc


def _org(name: str, identifiers: list | None = None) -> dict:
    return {"@type": "schema:Organization", "name": name, "schema:identifier": identifiers or []}


def _person(name: str, identifiers: list | None = None) -> dict:
    return {"@type": "schema:Person", "name": name, "schema:identifier": identifiers or []}


MINIMAL_VALID_FIELDS = {
    "schema:name": "A Title",
    "schema:description": "A description.",
    "schema:license": [{"name": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0"}],
    "schema:url": "https://example.org/dataset",
    "schema:creator": [_org("Someone")],
    "schema:datePublished": "2020",
    "schema:distribution": [
        {"contentUrl": "https://example.org/data.csv", "encodingFormat": "text/csv"}
    ],
}


class TestEnvelope:
    def test_emits_context_type_and_conforms_to(self):
        doc = make_document(**MINIMAL_VALID_FIELDS)
        result = to_croissant_json(doc)
        assert result.croissant_json["@type"] == "sc:Dataset"
        assert result.croissant_json["conformsTo"] == CROISSANT_CONFORMS_TO
        context = result.croissant_json["@context"]
        assert context["@vocab"] == "http://schema.org/"
        assert context["cr"] == "http://mlcommons.org/croissant/"
        assert context["sc"] == "http://schema.org/"
        assert context["conformsTo"] == "dct:conformsTo"

    def test_no_warnings_when_every_required_field_present(self):
        doc = make_document(**MINIMAL_VALID_FIELDS)
        result = to_croissant_json(doc)
        assert result.warnings == []

    def test_token_usage_is_always_zero(self):
        doc = make_document(**MINIMAL_VALID_FIELDS)
        result = to_croissant_json(doc)
        assert result.token_usage == TokenUsage()

    def test_never_raises_on_a_completely_empty_document(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert isinstance(result, CroissantExportResult)
        assert result.croissant_json["name"] == "Untitled resource"

    def test_carries_top_level_id_when_present(self):
        doc = make_document(**MINIMAL_VALID_FIELDS, **{"@id": "https://example.org/dataset#record"})
        result = to_croissant_json(doc)
        assert result.croissant_json["@id"] == "https://example.org/dataset#record"

    def test_no_id_key_when_absent(self):
        doc = make_document(**MINIMAL_VALID_FIELDS)
        result = to_croissant_json(doc)
        assert "@id" not in result.croissant_json


class TestName:
    def test_prefers_schema_name(self):
        doc = make_document(**{"schema:name": "A Title"})
        result = to_croissant_json(doc)
        assert result.croissant_json["name"] == "A Title"
        assert not any("no schema:name" in w for w in result.warnings)

    def test_falls_back_to_identifier_value_when_no_name(self):
        doc = make_document(
            **{"schema:identifier": [{"propertyID": "URL", "value": "https://example.org/x"}]}
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["name"] == "https://example.org/x"
        assert any("no schema:name found" in w for w in result.warnings)

    def test_falls_back_to_untitled_when_nothing_at_all(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert result.croissant_json["name"] == "Untitled resource"


class TestDescription:
    def test_maps_the_description(self):
        doc = make_document(**{"schema:description": "First."})
        result = to_croissant_json(doc)
        assert result.croissant_json["description"] == "First."

    def test_placeholder_with_warning_when_missing(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert result.croissant_json["description"] == "No description was extracted for this resource."
        assert any("no schema:description found" in w for w in result.warnings)


class TestLicense:
    def test_prefers_url_over_name(self):
        doc = make_document(
            **{"schema:license": [{"name": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0"}]}
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["license"] == ["https://creativecommons.org/publicdomain/zero/1.0"]

    def test_falls_back_to_name_when_no_url(self):
        doc = make_document(**{"schema:license": [{"name": "Datos Abiertos de Chile", "url": ""}]})
        result = to_croissant_json(doc)
        assert result.croissant_json["license"] == ["Datos Abiertos de Chile"]

    def test_maps_multiple_license_entries(self):
        doc = make_document(
            **{
                "schema:license": [
                    {"name": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0"},
                    {"name": "ODbL", "url": ""},
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["license"] == [
            "https://creativecommons.org/publicdomain/zero/1.0",
            "ODbL",
        ]

    def test_omits_field_and_warns_when_missing_rather_than_fabricating(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "license" not in result.croissant_json
        assert any("no schema:license found" in w for w in result.warnings)


class TestUrl:
    def test_maps_schema_url(self):
        doc = make_document(**{"schema:url": "https://example.org/dataset"})
        result = to_croissant_json(doc)
        assert result.croissant_json["url"] == "https://example.org/dataset"

    def test_resolves_doi_identifier_through_doi_org_when_no_url(self):
        doc = make_document(
            **{"schema:identifier": [{"propertyID": "DOI", "value": "10.5880/GFZ.2.4.2021.001"}]}
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["url"] == "https://doi.org/10.5880/GFZ.2.4.2021.001"

    def test_falls_back_to_identifier_url_field(self):
        doc = make_document(
            **{
                "schema:identifier": [
                    {"propertyID": "URL", "value": "x", "url": "https://example.org/x"}
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["url"] == "https://example.org/x"

    def test_omits_field_and_warns_when_nothing_resolvable(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "url" not in result.croissant_json
        assert any("no schema:url" in w for w in result.warnings)


class TestCreators:
    def test_maps_organization_and_person_types(self):
        doc = make_document(**{"schema:creator": [_org("An Org"), _person("A Person")]})
        result = to_croissant_json(doc)
        creators = result.croissant_json["creator"]
        assert creators[0] == {"@type": "sc:Organization", "name": "An Org"}
        assert creators[1] == {"@type": "sc:Person", "name": "A Person"}

    def test_includes_identifier_url_when_present(self):
        doc = make_document(
            **{
                "schema:creator": [
                    _org("An Org", identifiers=[{"propertyID": "ROR", "value": "0x", "url": "https://ror.org/0x"}])
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["creator"][0]["url"] == "https://ror.org/0x"

    def test_tolerates_at_list_wrapped_shape(self):
        """Defensive: docs/cdif_pivot_implementation_plan.md's C4 draft
        assumed {"@list": [...]}, but the shipped schema is a bare list
        (see module docstring) -- both must work."""
        doc = make_document(**{"schema:creator": {"@list": [_org("An Org")]}})
        result = to_croissant_json(doc)
        assert result.croissant_json["creator"] == [{"@type": "sc:Organization", "name": "An Org"}]

    def test_omits_field_and_warns_when_no_creators(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "creator" not in result.croissant_json
        assert any("no schema:creator found" in w for w in result.warnings)

    def test_skips_entries_with_no_name(self):
        doc = make_document(**{"schema:creator": [{"@type": "schema:Organization", "name": ""}]})
        result = to_croissant_json(doc)
        assert "creator" not in result.croissant_json


class TestDatePublished:
    def test_maps_date_published(self):
        doc = make_document(**{"schema:datePublished": "2020-01-01"})
        result = to_croissant_json(doc)
        assert result.croissant_json["datePublished"] == "2020-01-01"

    def test_falls_back_to_date_created_with_warning(self):
        doc = make_document(**{"schema:dateCreated": "2019"})
        result = to_croissant_json(doc)
        assert result.croissant_json["datePublished"] == "2019"
        assert any("falling back to schema:dateCreated" in w for w in result.warnings)

    def test_omits_field_and_warns_when_neither_present(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "datePublished" not in result.croissant_json
        assert any("no schema:datePublished or schema:dateCreated found" in w for w in result.warnings)


class TestDistribution:
    def test_maps_content_url_and_encoding_format(self):
        doc = make_document(
            **{
                "schema:distribution": [
                    {"contentUrl": "https://example.org/data.csv", "encodingFormat": "text/csv"}
                ]
            }
        )
        result = to_croissant_json(doc)
        entry = result.croissant_json["distribution"][0]
        assert entry["@type"] == "cr:FileObject"
        assert entry["@id"] == "https://example.org/data.csv"
        assert entry["contentUrl"] == "https://example.org/data.csv"
        assert entry["encodingFormat"] == "text/csv"

    def test_maps_content_size(self):
        doc = make_document(
            **{
                "schema:distribution": [
                    {
                        "contentUrl": "https://example.org/data.zip",
                        "contentSize": [{"size": 2.5, "unit": "MB"}],
                    }
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["distribution"][0]["contentSize"] == "2.5 MB"

    def test_maps_sha256_checksum_by_length(self):
        checksum = "a" * 64
        doc = make_document(
            **{
                "schema:distribution": [
                    {"contentUrl": "https://example.org/data.csv", "checksum": checksum}
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["distribution"][0]["sha256"] == checksum

    def test_maps_md5_checksum_by_length(self):
        checksum = "b" * 32
        doc = make_document(
            **{
                "schema:distribution": [
                    {"contentUrl": "https://example.org/data.csv", "checksum": checksum}
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["distribution"][0]["md5"] == checksum

    def test_unrecognized_checksum_length_is_not_emitted_but_warned(self):
        checksum = "c" * 40  # sha-1 length -- no Croissant-recognized property
        doc = make_document(
            **{
                "schema:distribution": [
                    {"contentUrl": "https://example.org/data.csv", "checksum": checksum}
                ]
            }
        )
        result = to_croissant_json(doc)
        entry = result.croissant_json["distribution"][0]
        assert "sha256" not in entry
        assert "md5" not in entry
        assert any("isn't recognizable as md5/sha256" in w for w in result.warnings)

    def test_skips_entries_with_no_content_url(self):
        doc = make_document(**{"schema:distribution": [{"encodingFormat": "text/csv"}]})
        result = to_croissant_json(doc)
        assert "distribution" not in result.croissant_json

    def test_omits_field_and_warns_when_empty(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "distribution" not in result.croissant_json
        assert any("no usable schema:distribution entries found" in w for w in result.warnings)

    def test_never_fabricates_a_record_set(self):
        """recordSet is Croissant's per-column/field structure description
        -- blocked on a structure-fetcher enricher that doesn't exist yet
        (see module docstring). Must never appear, empty or otherwise."""
        doc = make_document(**MINIMAL_VALID_FIELDS)
        result = to_croissant_json(doc)
        assert "recordSet" not in result.croissant_json


class TestRecommendedFields:
    def test_maps_keywords_by_name(self):
        doc = make_document(
            **{"schema:keywords": [{"name": "Gastos municipales"}, {"name": "Presupuesto"}]}
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["keywords"] == ["Gastos municipales", "Presupuesto"]

    def test_no_keywords_key_when_empty(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "keywords" not in result.croissant_json

    def test_maps_publisher(self):
        doc = make_document(**{"schema:publisher": _org("A Publisher")})
        result = to_croissant_json(doc)
        assert result.croissant_json["publisher"] == {"@type": "sc:Organization", "name": "A Publisher"}

    def test_no_publisher_key_when_absent(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "publisher" not in result.croissant_json

    def test_maps_version_date_created_date_modified(self):
        doc = make_document(
            **{
                "schema:version": "1.0",
                "schema:dateCreated": "2019",
                "schema:dateModified": "2020-01-01",
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["version"] == "1.0"
        assert result.croissant_json["dateCreated"] == "2019"
        assert result.croissant_json["dateModified"] == "2020-01-01"

    def test_maps_same_as_by_value(self):
        doc = make_document(**{"schema:sameAs": [{"value": "EPF-2021", "name": "EPF"}]})
        result = to_croissant_json(doc)
        assert result.croissant_json["sameAs"] == ["EPF-2021"]

    def test_no_same_as_key_when_empty(self):
        doc = MetadataDocument()
        result = to_croissant_json(doc)
        assert "sameAs" not in result.croissant_json

    def test_maps_in_language(self):
        doc = make_document(**{"schema:inLanguage": "es"})
        result = to_croissant_json(doc)
        assert result.croissant_json["inLanguage"] == "es"


GOLDEN_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "golden" / "expected"


class TestAgainstRealGoldenFixtures:
    """Not synthetic -- the actual committed golden fixture outputs from a
    real CDIF-generating pipeline run, same fixtures test_dataverse_export.py
    exercises."""

    def test_produces_a_valid_shape_from_every_real_fixture(self):
        fixture_paths = sorted(GOLDEN_FIXTURES_DIR.glob("*.json"))
        if not fixture_paths:
            pytest.skip("no golden fixtures present in this checkout")

        for fixture_path in fixture_paths:
            data = json.loads(fixture_path.read_text(encoding="utf-8"))
            doc = MetadataDocument()
            for key, value in data.items():
                doc.set_field(key, value)

            result = to_croissant_json(doc)

            assert result.croissant_json["@type"] == "sc:Dataset"
            assert result.croissant_json["conformsTo"] == CROISSANT_CONFORMS_TO
            assert result.croissant_json["name"]
            assert result.croissant_json["description"]
            assert "recordSet" not in result.croissant_json
            assert isinstance(result.warnings, list)
            assert result.token_usage == TokenUsage()

    def test_sample_input01_maps_creator_and_distribution_omitted(self):
        fixture_path = GOLDEN_FIXTURES_DIR / "sample_input01.json"
        if not fixture_path.is_file():
            pytest.skip("golden fixture not present in this checkout")
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        doc = MetadataDocument()
        for key, value in data.items():
            doc.set_field(key, value)

        result = to_croissant_json(doc)

        assert result.croissant_json["name"] == "Gastos municipales (presupuesto abierto)"
        assert result.croissant_json["creator"][0]["name"] == "Ministerio de Hacienda"
        # This fixture's schema:distribution is empty and schema:url is
        # null -- but its schema:identifier carries a resolvable URL, so
        # url is still populated even though distribution is omitted.
        assert "distribution" not in result.croissant_json
        assert any("no usable schema:distribution entries found" in w for w in result.warnings)
        assert result.croissant_json["url"] == (
            "https://datos.gob.cl/dataset/"
            "gastos-municipales-presas-corporaciones-municipales-presupuesto-abierto"
        )
