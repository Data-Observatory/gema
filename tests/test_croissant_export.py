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
    return {"@type": ["schema:Organization"], "schema:name": name, "schema:identifier": identifiers or []}


def _person(name: str, identifiers: list | None = None) -> dict:
    return {"@type": ["schema:Person"], "schema:name": name, "schema:identifier": identifiers or []}


MINIMAL_VALID_FIELDS = {
    "schema:name": "A Title",
    "schema:description": "A description.",
    "schema:license": [{"schema:name": "CC0", "schema:url": "https://creativecommons.org/publicdomain/zero/1.0"}],
    "schema:url": "https://example.org/dataset",
    "schema:creator": [_org("Someone")],
    "schema:datePublished": "2020",
    "schema:distribution": [
        {"schema:contentUrl": "https://example.org/data.csv", "schema:encodingFormat": "text/csv"}
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
            **{"schema:identifier": [{"schema:propertyID": "URL", "schema:value": "https://example.org/x"}]}
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
            **{"schema:license": [{"schema:name": "CC0", "schema:url": "https://creativecommons.org/publicdomain/zero/1.0"}]}
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["license"] == ["https://creativecommons.org/publicdomain/zero/1.0"]

    def test_falls_back_to_name_when_no_url(self):
        doc = make_document(**{"schema:license": [{"schema:name": "Datos Abiertos de Chile", "schema:url": ""}]})
        result = to_croissant_json(doc)
        assert result.croissant_json["license"] == ["Datos Abiertos de Chile"]

    def test_maps_multiple_license_entries(self):
        doc = make_document(
            **{
                "schema:license": [
                    {"schema:name": "CC0", "schema:url": "https://creativecommons.org/publicdomain/zero/1.0"},
                    {"schema:name": "ODbL", "schema:url": ""},
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

    def test_accepts_a_bare_string_license(self):
        """The vendored schema allows schema:license as a bare string or
        {"@id": ...}, not just the dict shape gema's own generation always
        produces -- iterating an un-guarded string used to silently walk
        its characters instead of being read as a single value."""
        doc = make_document(**{"schema:license": "CC-BY-4.0"})
        result = to_croissant_json(doc)
        assert result.croissant_json["license"] == ["CC-BY-4.0"]

    def test_accepts_a_bare_id_reference_license(self):
        doc = make_document(**{"schema:license": {"@id": "https://creativecommons.org/licenses/by/4.0/"}})
        result = to_croissant_json(doc)
        assert result.croissant_json["license"] == ["https://creativecommons.org/licenses/by/4.0/"]


class TestUrl:
    def test_maps_schema_url(self):
        doc = make_document(**{"schema:url": "https://example.org/dataset"})
        result = to_croissant_json(doc)
        assert result.croissant_json["url"] == "https://example.org/dataset"

    def test_resolves_doi_identifier_through_doi_org_when_no_url(self):
        doc = make_document(
            **{"schema:identifier": [{"schema:propertyID": "DOI", "schema:value": "10.5880/GFZ.2.4.2021.001"}]}
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["url"] == "https://doi.org/10.5880/GFZ.2.4.2021.001"

    def test_falls_back_to_identifier_url_field(self):
        doc = make_document(
            **{
                "schema:identifier": [
                    {"schema:propertyID": "URL", "schema:value": "x", "schema:url": "https://example.org/x"}
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

    def test_doi_entry_url_preferred_over_constructing_one(self):
        """docs/cdif_pivot_implementation_plan.md Backlog: prefer
        schema:url on the identifier entry itself before falling back to
        constructing a doi.org URL from the bare value."""
        doc = make_document(
            **{
                "schema:identifier": [
                    {
                        "schema:propertyID": "DOI",
                        "schema:value": "10.5880/GFZ.2.4.2021.001",
                        "schema:url": "https://doi.org/10.5880/GFZ.2.4.2021.001",
                    }
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["url"] == "https://doi.org/10.5880/GFZ.2.4.2021.001"

    def test_doi_value_already_a_full_url_is_not_double_prefixed(self):
        """DOI double-prefix guard (docs/cdif_pivot_implementation_plan.md
        Backlog): if schema:value is already a full URL (no schema:url on
        the entry to prefer instead), _build_url must not prepend
        https://doi.org/ a second time."""
        doc = make_document(
            **{
                "schema:identifier": [
                    {
                        "schema:propertyID": "DOI",
                        "schema:value": "https://doi.org/10.5880/GFZ.2.4.2021.001",
                    }
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["url"] == "https://doi.org/10.5880/GFZ.2.4.2021.001"


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
                    _org("An Org", identifiers=[{"schema:propertyID": "ROR", "schema:value": "0x", "schema:url": "https://ror.org/0x"}])
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
        doc = make_document(**{"schema:creator": [{"@type": ["schema:Organization"], "schema:name": ""}]})
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
                    {"schema:contentUrl": "https://example.org/data.csv", "schema:encodingFormat": "text/csv"}
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
                        "schema:contentUrl": "https://example.org/data.zip",
                        "schema:contentSize": [{"size": 2.5, "unit": "MB"}],
                    }
                ]
            }
        )
        result = to_croissant_json(doc)
        assert result.croissant_json["distribution"][0]["contentSize"] == "2.5 MB"

    def test_maps_content_size_when_shaped_as_a_dict(self):
        """config/agents.yaml's media_files prompt actually emits
        schema:contentSize as a single dict, not a list -- indexing a dict
        by 0 used to raise KeyError, a real crash this regression guards."""
        doc = make_document(
            **{
                "schema:distribution": [
                    {
                        "schema:contentUrl": "https://example.org/data.zip",
                        "schema:contentSize": {"size": 2.5, "unit": "MB"},
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
                    {"schema:contentUrl": "https://example.org/data.csv", "checksum": checksum}
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
                    {"schema:contentUrl": "https://example.org/data.csv", "checksum": checksum}
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
                    {"schema:contentUrl": "https://example.org/data.csv", "checksum": checksum}
                ]
            }
        )
        result = to_croissant_json(doc)
        entry = result.croissant_json["distribution"][0]
        assert "sha256" not in entry
        assert "md5" not in entry
        assert any("isn't recognizable as md5/sha256" in w for w in result.warnings)

    def test_skips_entries_with_no_content_url(self):
        doc = make_document(**{"schema:distribution": [{"schema:encodingFormat": "text/csv"}]})
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
            **{"schema:keywords": [{"schema:name": "Gastos municipales"}, {"schema:name": "Presupuesto"}]}
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
        doc = make_document(**{"schema:sameAs": [{"schema:value": "EPF-2021", "schema:name": "EPF"}]})
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
GOLDEN_FIXTURE_PATHS = sorted(GOLDEN_FIXTURES_DIR.glob("sample_input0*.json"))

# Real, per-fixture expected values -- confirmed by reading each fixture's
# actual schema:name/schema:creator/schema:license before writing these
# (not guessed), so a broken mapping on any one fixture can't pass
# silently. sample_input02.json's recording used to be fully degenerate
# (no schema:name/creator/license/identifier at all); a real
# `make record-golden` re-run (2026-09-07, no code changes -- opencode has
# no seed) produced a populated recording instead. Kept as a live example
# that this corpus's non-determinism can turn a degenerate case into a
# populated one between recordings, not because the earlier expectations
# were wrong for the fixture they described at the time.
GOLDEN_EXPECTATIONS: dict[str, dict] = {
    "sample_input01": {
        "name": "Gastos municipales (presupuesto abierto)",
        "creator_names": ["Ministerio de Hacienda"],
        "license": ["Datos Abiertos del Estado de Chile"],
    },
    "sample_input02": {
        "name": (
            "Rasgos-CL: Plataforma de Rasgos Funcionales de la Biodiversidad "
            "de Plantas en Chile"
        ),
        "creator_names": ["Data Observatory Foundation"],
        "license": None,
    },
    "sample_input03": {
        "name": "Zonas climaticas de Chile segun Köppen-Geiger escala 1:1.500.000",
        "creator_names": ["Sarricolea, P.", "Herrera, MJ.", "Meseguer-Ruiz, O."],
        "license": None,
    },
    "sample_input04": {
        "name": "Encuesta de Presupuestos Familiares",
        "creator_names": ["Instituto Nacional de Estadísticas"],
        "license": None,
    },
    "sample_input05": {
        "name": "Censo Agropecuario 2007 Ganado bovino Isla de Pascua",
        # Was "Instituto de Políticas y Bienes Públicos" (a Madrid research
        # facility, wrong country/institution) before the O-5 ROR
        # affiliation-match country sanity check fix -- this real
        # re-recording (2026-09-07) now resolves the actual Chilean
        # publisher (ODEPA) via ISNI instead, confirming the fix. See
        # docs/cdif_pivot_implementation_plan.md's O-5 section.
        "creator_names": ["Oficina de Estudios y Políticas Agrarias"],
        "license": None,
    },
    "sample_input06": {
        "name": (
            "Active fault database for the Atacama Fault System (N-Chile) as "
            "basis for tracking forearc segmentation"
        ),
        "creator_names": ["Mittelstädt, Jana", "Victor, Pia"],
        "license": None,
    },
}


class TestAgainstRealGoldenFixtures:
    """Not synthetic -- the actual committed golden fixture outputs from a
    real CDIF-generating pipeline run, same fixtures test_dataverse_export.py
    exercises.

    Parametrized (not a single for-loop) so a failure on one fixture
    doesn't hide failures on the others (Opus review, 2026-09-04) -- and
    each case asserts real mapped values (name, creator names, license),
    not just shape/truthiness checks that a broken mapping could still
    satisfy."""

    @pytest.mark.parametrize("fixture_path", GOLDEN_FIXTURE_PATHS, ids=lambda p: p.stem)
    def test_real_fixture_maps_expected_values(self, fixture_path: Path):
        if not GOLDEN_FIXTURE_PATHS:
            pytest.skip("no golden fixtures present in this checkout")
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        doc = MetadataDocument()
        for key, value in data.items():
            doc.set_field(key, value)

        result = to_croissant_json(doc)
        expected = GOLDEN_EXPECTATIONS[fixture_path.stem]

        assert result.croissant_json["@type"] == "sc:Dataset"
        assert result.croissant_json["conformsTo"] == CROISSANT_CONFORMS_TO
        assert result.croissant_json["name"] == expected["name"]
        assert result.croissant_json["description"]
        assert "recordSet" not in result.croissant_json
        assert isinstance(result.warnings, list)
        assert result.token_usage == TokenUsage()

        creator_names = [c["name"] for c in result.croissant_json.get("creator", [])]
        assert creator_names == expected["creator_names"]

        assert result.croissant_json.get("license") == expected["license"]

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


class TestMalformedInputNeverRaises:
    """Mirrors test_datacite_export.py::test_malformed_types_never_raise --
    croissant.py had no equivalent (Opus review, 2026-09-04). This is
    exactly the kind of test that would have caught the
    schema:contentSize-as-dict crash before it was found by inspection
    (see TestDistribution.test_maps_content_size_when_shaped_as_a_dict)."""

    def test_malformed_types_never_raise(self):
        doc = make_document(
            **{
                "schema:name": 12345,
                "schema:description": ["a", "list", "not", "a", "string"],
                "schema:creator": "not a list",
                "schema:license": 42,
                "schema:distribution": "not a list",
                "schema:keywords": {"not": "a list of dicts"},
                "schema:identifier": "not a list",
                "schema:sameAs": 7,
                "schema:publisher": "not a dict",
            }
        )
        result = to_croissant_json(doc)
        assert isinstance(result, CroissantExportResult)
        assert isinstance(result.croissant_json, dict)
        assert "creator" not in result.croissant_json
        assert "distribution" not in result.croissant_json
        assert "recordSet" not in result.croissant_json

    def test_distribution_entries_that_are_not_dicts_are_skipped(self):
        doc = make_document(**{"schema:distribution": ["not a dict", 42, None, {}]})
        result = to_croissant_json(doc)
        assert "distribution" not in result.croissant_json

    def test_none_document_fields_never_raise(self):
        doc = make_document(
            **{
                "schema:name": None,
                "schema:creator": None,
                "schema:distribution": None,
                "schema:license": None,
            }
        )
        result = to_croissant_json(doc)
        assert isinstance(result, CroissantExportResult)
