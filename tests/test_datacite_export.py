"""Tests for exporters/datacite.py -- CDIF-shaped MetadataDocument ->
DataCite 4.6 native dict.

Fixtures are built as CDIF JSON-LD shaped dicts (CURIE-keyed, matching
what CDIFDiscoveryProfile.merge_agent_results actually produces -- see
tests/test_cdif_discovery_schema.py and the real recorded golden fixtures
under tests/fixtures/golden/expected/*.json) -- never DataCite-shaped
fixtures, which would let a broken reverse mapping pass silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from metadata_enricher.exporters.datacite import (
    DataCiteExportResult,
    _get_datacite_schema,
    to_datacite_json,
)
from metadata_enricher.schemas.datacite import DataCiteSchema46
from metadata_enricher.types import MetadataDocument, TokenUsage


def make_document(**fields: object) -> MetadataDocument:
    doc = MetadataDocument()
    for key, value in fields.items():
        doc.set_field(key, value)
    return doc


def _org(name: str, identifiers: list | None = None) -> dict:
    return {"@type": ["schema:Organization"], "schema:name": name, "schema:identifier": identifiers or []}


def _person(name: str, given: str, family: str, identifiers: list | None = None) -> dict:
    return {
        "@type": ["schema:Person"],
        "schema:name": name,
        "schema:givenName": given,
        "schema:familyName": family,
        "schema:identifier": identifiers or [],
    }


def _fields(result: DataCiteExportResult) -> dict:
    return result.datacite_json


class TestSingleton:
    def test_get_datacite_schema_returns_same_instance(self):
        first = _get_datacite_schema()
        second = _get_datacite_schema()
        assert first is second
        assert isinstance(first, DataCiteSchema46)


class TestTitlesAndDescriptions:
    def test_maps_name_and_description(self):
        doc = make_document(**{
            "schema:name": "A Title",
            "schema:description": "A description.",
            "schema:inLanguage": "es",
            "@id": "https://example.org/x",
            "schema:creator": [_org("Someone")],
        })
        result = to_datacite_json(doc)
        data = _fields(result)
        assert data["titles"] == [{"name": "A Title", "title_type": "MainTitle", "language": "es"}]
        assert data["descriptions"][0]["description"] == "A description."
        assert data["descriptions"][0]["description_type"] == "Abstract"
        assert result.warnings == []

    def test_warns_and_empty_titles_when_no_name(self):
        doc = make_document(**{"schema:description": "D."})
        result = to_datacite_json(doc)
        data = _fields(result)
        assert data["titles"] == []
        assert any("no schema:name found" in w for w in result.warnings)

    def test_warns_when_no_description(self):
        doc = make_document(**{"schema:name": "T"})
        result = to_datacite_json(doc)
        assert any("no schema:description found" in w for w in result.warnings)

    def test_measurement_technique_becomes_methods_description(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:description": "D.",
            "schema:measurementTechnique": ["Remote sensing", "Field survey"],
        })
        result = to_datacite_json(doc)
        data = _fields(result)
        method_descriptions = [
            d["description"] for d in data["descriptions"] if d["description_type"] == "Methods"
        ]
        assert method_descriptions == ["Remote sensing", "Field survey"]


class TestCreatorsC4Reversal:
    def test_bare_list_creator_maps_to_creators(self):
        """CDIFDiscoveryProfile actually emits schema:creator as a bare
        list today (confirmed against the real golden fixtures) -- this
        must round-trip correctly."""
        doc = make_document(**{
            "schema:name": "T",
            "schema:creator": [_org("Ministerio de Hacienda")],
        })
        result = to_datacite_json(doc)
        data = _fields(result)
        assert len(data["creators"]) == 1
        assert data["creators"][0]["creator_name"] == "Ministerio de Hacienda"
        assert data["creators"][0]["creator_name_type"] == "Organizational"

    def test_at_list_wrapped_creator_also_unwraps(self):
        """The vendored schema.json's own field description asks for the
        {"@list": [...]} JSON-LD construct to preserve author order -- a
        document carrying that shape (even though today's generation code
        doesn't produce it) must still map correctly, not silently drop
        every creator."""
        doc = make_document(**{
            "schema:name": "T",
            "schema:creator": {"@list": [_org("First Author"), _org("Second Author")]},
        })
        result = to_datacite_json(doc)
        data = _fields(result)
        names = [c["creator_name"] for c in data["creators"]]
        assert names == ["First Author", "Second Author"]

    def test_person_creator_maps_personal_type_and_names(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:creator": [_person("Sarricolea, Pablo", "Pablo", "Sarricolea")],
        })
        result = to_datacite_json(doc)
        entry = _fields(result)["creators"][0]
        assert entry["creator_name_type"] == "Personal"
        assert entry["given_name"] == "Pablo"
        assert entry["family_name"] == "Sarricolea"
        assert entry["type"] == "Person"

    def test_creator_identifiers_and_affiliations_map_through(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:creator": [
                _org(
                    "Ministerio de Hacienda",
                    identifiers=[{"schema:propertyID": "ISNI", "schema:value": "123", "schema:url": "https://isni.org/123"}],
                )
                | {"schema:affiliation": [_org("Gobierno de Chile")]}
            ],
        })
        result = to_datacite_json(doc)
        entry = _fields(result)["creators"][0]
        assert entry["name_identifiers"] == [
            {"name_identifier": "123", "name_identifier_scheme": "ISNI", "scheme_uri": "https://isni.org/123"}
        ]
        assert entry["affiliations"][0]["affiliation"] == "Gobierno de Chile"

    def test_no_creators_warns(self):
        doc = make_document(**{"schema:name": "T", "schema:creator": []})
        result = to_datacite_json(doc)
        assert any("no schema:creator entries found" in w for w in result.warnings)


class TestPublishersC3Reversal:
    def test_single_publisher_object_becomes_publishers_list(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:publisher": _org(
                "Data Observatory Foundation",
                identifiers=[{"schema:propertyID": "ROR", "schema:value": "https://ror.org/027nn6b17", "schema:url": "u"}],
            ),
        })
        result = to_datacite_json(doc)
        publishers = _fields(result)["publishers"]
        assert len(publishers) == 1
        assert publishers[0]["publisher_name"] == "Data Observatory Foundation"
        assert publishers[0]["publisher_identifier"] == "https://ror.org/027nn6b17"
        assert publishers[0]["publisher_identifier_scheme"] == "ROR"

    def test_provider_overflow_appended_to_publishers(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:publisher": _org("Main Publisher"),
            "schema:provider": [_org("Overflow Publisher")],
        })
        result = to_datacite_json(doc)
        names = [p["publisher_name"] for p in _fields(result)["publishers"]]
        assert names == ["Main Publisher", "Overflow Publisher"]

    def test_empty_publisher_object_produces_no_entry(self):
        doc = make_document(**{"schema:name": "T", "schema:publisher": {}})
        result = to_datacite_json(doc)
        assert _fields(result)["publishers"] == []


class TestSameAsVsRelatedLinkStayDistinct:
    def test_same_as_maps_to_alternate_identifiers_only(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:sameAs": [{"schema:value": "EPF-2021", "schema:name": "EPF"}],
            "schema:relatedLink": [
                {"schema:linkRelationship": "IsDescribedBy", "schema:target": {"schema:url": "https://api.example.org/docs", "schema:name": "API"}}
            ],
        })
        result = to_datacite_json(doc)
        data = _fields(result)
        assert data["alternate_identifiers"] == [
            {"alternate_name": "EPF", "alternate_identifier": "EPF-2021", "alternate_identifier_type": "Local"}
        ]
        related = data["related_identifiers"][0]
        assert related["related_identifier"] == "https://api.example.org/docs"
        assert related["related_identifier_type"] == "URL"
        assert related["relation_type"] == "IsDescribedBy"
        # Distinct lists -- neither field leaked into the other.
        assert len(data["alternate_identifiers"]) == 1
        assert len(data["related_identifiers"]) == 1

    def test_same_as_url_value_gets_url_type(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:sameAs": [{"schema:value": "https://example.org/dup", "schema:name": ""}],
        })
        result = to_datacite_json(doc)
        assert _fields(result)["alternate_identifiers"][0]["alternate_identifier_type"] == "URL"

    def test_prov_was_derived_from_maps_to_is_derived_from_relation(self):
        doc = make_document(**{
            "schema:name": "T",
            "prov:wasDerivedFrom": [{"schema:url": "https://example.org/source-dataset"}],
        })
        result = to_datacite_json(doc)
        related = _fields(result)["related_identifiers"][0]
        assert related["related_identifier"] == "https://example.org/source-dataset"
        assert related["related_identifier_type"] == "URL"
        assert related["relation_type"] == "IsDerivedFrom"

    def test_thumbnail_related_link_excluded_from_related_identifiers(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:relatedLink": [
                {"schema:linkRelationship": "thumbnail", "schema:target": {"schema:url": "https://example.org/thumb.png"}}
            ],
        })
        result = to_datacite_json(doc)
        data = _fields(result)
        assert data["resource"]["thumbnail"] == "https://example.org/thumb.png"
        assert data["related_identifiers"] == []


class TestEnvelopeFields:
    def test_at_id_and_identifier_map_into_resource(self):
        doc = make_document(**{
            "@id": "https://example.org/dataset/1",
            "schema:name": "T",
            "schema:identifier": [
                {"schema:propertyID": "URL", "schema:value": "https://example.org/dataset/1", "schema:url": "https://example.org/dataset/1"}
            ],
        })
        result = to_datacite_json(doc)
        resource = _fields(result)["resource"]
        assert resource["identifier"] == "https://example.org/dataset/1"
        assert resource["identifier_type"] == "URL"

    def test_doi_identifier_preferred_over_url(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:identifier": [
                {"schema:propertyID": "URL", "schema:value": "https://example.org/x", "schema:url": "https://example.org/x"},
                {"schema:propertyID": "DOI", "schema:value": "10.5880/GFZ.1", "schema:url": "https://doi.org/10.5880/GFZ.1"},
            ],
        })
        result = to_datacite_json(doc)
        resource = _fields(result)["resource"]
        assert resource["identifier"] == "10.5880/GFZ.1"
        assert resource["identifier_type"] == "DOI"

    def test_falls_back_to_at_id_when_no_schema_identifier(self):
        doc = make_document(**{"@id": "https://example.org/fallback", "schema:name": "T"})
        result = to_datacite_json(doc)
        resource = _fields(result)["resource"]
        assert resource["identifier"] == "https://example.org/fallback"

    def test_missing_identifier_entirely_warns(self):
        doc = make_document(**{"schema:name": "T"})
        result = to_datacite_json(doc)
        assert any("no schema:identifier or @id found" in w for w in result.warnings)

    def test_date_modified_maps_to_updated_date(self):
        doc = make_document(**{"schema:name": "T", "schema:dateModified": "2026-09-04"})
        result = to_datacite_json(doc)
        dates = _fields(result)["dates"]
        assert {"date": "2026-09-04", "date_type": "Updated"} in [
            {k: v for k, v in d.items() if k in ("date", "date_type")} for d in dates
        ]

    def test_date_published_maps_to_publication_year_and_issued_date(self):
        doc = make_document(**{"schema:name": "T", "schema:datePublished": "2021-05-01"})
        result = to_datacite_json(doc)
        data = _fields(result)
        assert data["resource"]["publication_year"] == "2021"
        issued = [d for d in data["dates"] if d["date_type"] == "Issued"]
        assert issued[0]["date"] == "2021-05-01"

    def test_type_maps_to_resource_type_general(self):
        doc = make_document(**{"schema:name": "T", "@type": ["schema:Dataset"]})
        result = to_datacite_json(doc)
        assert _fields(result)["resource"]["resource_type_general"] == "Dataset"


class TestContributorRoles:
    def test_contact_person_and_producer_map_to_resource_fields(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:contributor": [
                {"schema:name": "Someone", "role": "ContactPerson", "schema:email": "someone@example.org"},
                {"schema:name": "Data Unit", "role": "Producer"},
            ],
        })
        result = to_datacite_json(doc)
        resource = _fields(result)["resource"]
        assert resource["contact"] == "Someone (someone@example.org)"
        assert resource["producer"] == "Data Unit"

    def test_unmapped_role_folds_into_creators_with_warning(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:creator": [_org("Main Creator")],
            "schema:contributor": [{"schema:name": "Data Curator Org", "role": "DataCurator"}],
        })
        result = to_datacite_json(doc)
        data = _fields(result)
        contributor_types = [c["contributor_type"] for c in data["creators"]]
        assert "DataCurator" in contributor_types
        assert any("unmapped role" in w for w in result.warnings)


class TestRightsAndFunding:
    def test_license_maps_to_rights(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:license": [
                {"schema:name": "CC BY 4.0", "schema:url": "https://creativecommons.org/licenses/by/4.0/", "schema:identifier": "CC-BY-4.0"}
            ],
            "schema:copyrightHolder": "Someone",
        })
        result = to_datacite_json(doc)
        rights = _fields(result)["rights"]
        assert rights[0]["rights"] == "CC BY 4.0"
        assert rights[0]["rights_uri"] == "https://creativecommons.org/licenses/by/4.0/"
        assert rights[0]["rights_identifier"] == "CC-BY-4.0"
        assert rights[0]["rights_holder"] == "Someone"

    def test_conditions_of_access_without_license_becomes_bare_rights_entry(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:conditionsOfAccess": [{"condition": "requires registration"}],
        })
        result = to_datacite_json(doc)
        rights = _fields(result)["rights"]
        assert rights[0]["rights_condition"] == "requires registration"

    def test_funding_maps_award_and_funder(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:funding": [
                {
                    "@type": ["schema:MonetaryGrant"],
                    "schema:name": "Project X",
                    "schema:identifier": [{"schema:propertyID": "award_number", "schema:value": "3220567"}],
                    "schema:description": "FONDECYT",
                    "schema:funder": _org("Agencia Nacional de Investigación y Desarrollo"),
                }
            ],
        })
        result = to_datacite_json(doc)
        ref = _fields(result)["funding_references"][0]
        assert ref["funder_name"] == "Agencia Nacional de Investigación y Desarrollo"
        assert ref["funding_stream"] == "FONDECYT"
        assert ref["award_number"] == "3220567"
        assert ref["award_title"] == "Project X"


class TestMediaFilesAndCollectionsCapitalization:
    def test_distribution_maps_to_media_files(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:distribution": [
                {
                    "schema:contentUrl": "https://example.org/data.csv",
                    "schema:encodingFormat": "text/csv",
                    "schema:contentSize": [{"size": 2.5, "unit": "MB"}],
                    "checksum": "abc123",
                    "temporal_resolution": "daily",
                }
            ],
        })
        result = to_datacite_json(doc)
        media = _fields(result)["media_files"][0]
        assert media["file_uri"] == "https://example.org/data.csv"
        assert media["checksum"] == "abc123"
        assert media["temporal_resolution"] == "daily"
        # physical_carrier is always the literal "digital" -- enforced by
        # DataCiteSchema46's own normalizer, not this exporter's mapping.
        assert media["physical_carrier"] == "digital"

    def test_collections_capitalization_survives_end_to_end(self):
        """Regression: DataCiteSchema46._normalize_media_files uses
        "Collections" with an intentional capital C (schemas/datacite.py) --
        this must survive the full CDIF -> DataCite reverse mapping, not
        get silently lowercased or dropped."""
        doc = make_document(**{
            "schema:name": "T",
            "schema:distribution": [
                {
                    "schema:contentUrl": "https://example.org/data.csv",
                    "schema:includedInDataCatalog": {"@id": "https://example.org/catalog", "schema:name": "Open Data Catalog"},
                }
            ],
        })
        result = to_datacite_json(doc)
        media = _fields(result)["media_files"][0]
        assert "Collections" in media
        assert "collections" not in media
        assert media["Collections"] == [
            {"@id": "https://example.org/catalog", "schema:name": "Open Data Catalog"}
        ]

    def test_no_distribution_means_empty_media_files(self):
        doc = make_document(**{"schema:name": "T"})
        result = to_datacite_json(doc)
        assert _fields(result)["media_files"] == []

    def test_resource_level_quality_metadata_without_distribution_warns(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:variableMeasured": [{"schema:name": "Rainfall"}],
        })
        result = to_datacite_json(doc)
        assert _fields(result)["media_files"] == []
        assert any("nothing to attach it to" in w for w in result.warnings)

    def test_variable_measured_and_technique_broadcast_onto_each_distribution(self):
        doc = make_document(**{
            "schema:name": "T",
            "schema:distribution": [
                {"schema:contentUrl": "https://example.org/a.csv"},
                {"schema:contentUrl": "https://example.org/b.csv"},
            ],
            "schema:variableMeasured": [{"schema:name": "Rainfall"}],
            "schema:measurementTechnique": ["Weather station"],
        })
        result = to_datacite_json(doc)
        media_files = _fields(result)["media_files"]
        assert len(media_files) == 2
        for media in media_files:
            assert media["variable_measured"] == [{"schema:name": "Rainfall"}]
            assert media["measurement_technique"] == ["Weather station"]


class TestGracefulDegradationOnEmptyDocument:
    def test_empty_document_produces_valid_shape_not_a_crash(self):
        doc = MetadataDocument()
        result = to_datacite_json(doc)
        data = _fields(result)
        assert data["titles"] == []
        assert data["creators"] == []
        assert data["resource"]["identifier"] == ""
        assert len(result.warnings) > 0
        assert result.token_usage == TokenUsage()

    def test_malformed_types_never_raise(self):
        """schema:creator as a plain string instead of a list/dict --
        must degrade gracefully, never raise."""
        doc = make_document(**{"schema:name": "T", "schema:creator": "not a list"})
        result = to_datacite_json(doc)
        assert isinstance(result, DataCiteExportResult)
        assert _fields(result)["creators"] == []


class TestTokenUsageAlwaysZero:
    def test_token_usage_is_zero_pure_crosswalk_no_llm_call(self):
        doc = make_document(**{"schema:name": "T"})
        result = to_datacite_json(doc)
        assert result.token_usage == TokenUsage()


GOLDEN_FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "expected" / "sample_input01.json"


class TestAgainstRealGoldenFixture:
    """Not a synthetic example -- the actual committed golden fixture
    output from a real CDIF-generating pipeline run."""

    def test_produces_a_valid_shape_from_real_output(self):
        if not GOLDEN_FIXTURE.is_file():
            import pytest

            pytest.skip("golden fixture not present in this checkout")
        raw = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        doc = MetadataDocument()
        for key, value in raw.items():
            doc.set_field(key, value)

        result = to_datacite_json(doc)
        data = _fields(result)

        assert data["titles"][0]["name"] == "Gastos municipales (presupuesto abierto)"
        assert data["creators"][0]["creator_name"] == "Ministerio de Hacienda"
        assert data["publishers"][0]["publisher_name"] == "Ministerio de Hacienda"
        assert data["resource"]["language"] == "es"
        assert data["resource"]["identifier"] == raw["@id"]
        # This real fixture's schema:license carries a name but no SPDX
        # identifier ("Datos Abiertos del Estado de Chile") -- confirms
        # the mapping doesn't fabricate one.
        assert data["rights"][0]["rights"] == "Datos Abiertos del Estado de Chile"
        assert data["rights"][0]["rights_identifier"] == ""
