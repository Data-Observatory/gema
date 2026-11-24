"""Tests for enrichers/grounding.py -- the check must flag invention, never valid rewordings."""

from __future__ import annotations

import pytest

from metadata_enricher.enrichers.grounding import (
    build_haystack,
    check_grounding,
    identifier_is_grounded,
    name_is_grounded,
    years_are_grounded,
)
from metadata_enricher.types import ResourceDescription


SOURCE = ResourceDescription(
    url="https://datos.example.cl/dataset/epf-2021",
    title="Encuesta de Presupuestos Familiares 2021",
    description=(
        "Publicada por el Instituto Nacional de Estadísticas (INE). "
        "Proyecto ANID FONDECYT 1234567. Servicio Nacional de Turismo, SERNATUR, colabora."
    ),
    fetched_content="Contacto: Universidad de Concepción, Facultad de Ingeniería. Año 2022.",
)


class TestValidVariantsAreNotFlagged:
    """The whole point: a correct value written differently must pass."""

    @pytest.mark.parametrize(
        "name",
        [
            "Instituto Nacional de Estadísticas",  # exact
            "instituto nacional de estadisticas",  # case + accents
            "Instituto Nacional de Estadística",  # singular/plural stem
            "Estadísticas, Instituto Nacional de",  # word order
            "INE",  # acronym given, expansion in source
            "SERNATUR",  # acronym present verbatim
            "Servicio Nacional de Turismo",  # expansion present
            "Universidad de Concepcion",  # accent dropped
            "Univ. de Concepción",  # abbreviation, shared words
            "Facultad de Ingenieria, Universidad de Concepción",  # extra words, most present
        ],
    )
    def test_grounded(self, name: str) -> None:
        assert name_is_grounded(name, build_haystack(SOURCE))

    def test_name_with_only_function_words_is_not_judged(self) -> None:
        assert name_is_grounded("de la", build_haystack(SOURCE))

    def test_empty_name_is_not_flagged(self) -> None:
        assert name_is_grounded("  ", build_haystack(SOURCE))

    def test_extra_input_fields_count_as_source(self) -> None:
        resource = ResourceDescription(title="x", publisher="Ministerio de Hacienda")
        assert name_is_grounded("Ministerio de Hacienda", build_haystack(resource))

    def test_context_hints_count_as_source(self) -> None:
        resource = ResourceDescription(
            title="x", context_hints={"affiliation": "Universidad Austral de Chile"}
        )
        assert name_is_grounded("Universidad Austral de Chile", build_haystack(resource))


class TestInventionIsFlagged:
    @pytest.mark.parametrize(
        "name",
        [
            "Ministerio de Hacienda",
            "Banco Central de Chile",
            "Pontificia Universidad Católica",
        ],
    )
    def test_not_grounded(self, name: str) -> None:
        assert not name_is_grounded(name, build_haystack(SOURCE))

    def test_short_acronym_does_not_match_by_chance_on_a_long_page(self) -> None:
        # "xyz" initials can occur somewhere in a long page; 3-letter acronym
        # expansion is only trusted against the short curated sources.
        page = " ".join(["Xavier Yanez Zamora"] * 3 + ["otra cosa"] * 3000)
        resource = ResourceDescription(title="t", fetched_content=page)
        # title/description do not contain an expansion of XYZ -> not grounded via expansion
        assert not name_is_grounded("QWX", build_haystack(resource))


class TestAwardIds:
    def test_found_verbatim(self) -> None:
        assert identifier_is_grounded("1234567", build_haystack(SOURCE))

    def test_separators_and_case_ignored(self) -> None:
        resource = ResourceDescription(title="Proyecto FONDECYT-1234.567")
        assert identifier_is_grounded("1234567", build_haystack(resource))
        assert identifier_is_grounded("fondecyt 1234567", build_haystack(resource))

    def test_invented_number(self) -> None:
        assert not identifier_is_grounded("7654321", build_haystack(SOURCE))


class TestYears:
    def test_year_in_source(self) -> None:
        assert years_are_grounded("2021-05-10", build_haystack(SOURCE))

    def test_range_needs_only_one_year(self) -> None:
        assert years_are_grounded("2019/2021", build_haystack(SOURCE))

    def test_year_absent(self) -> None:
        assert not years_are_grounded("2015", build_haystack(SOURCE))

    def test_value_without_year_is_not_judged(self) -> None:
        assert years_are_grounded("sin fecha", build_haystack(SOURCE))


class TestCheckGrounding:
    def test_flags_only_the_ungrounded_value_and_never_mutates(self) -> None:
        fields = {
            "schema:creator": {
                "@list": [
                    {"@type": ["schema:Organization"], "schema:name": "Instituto Nacional de Estadísticas"},
                    {"@type": ["schema:Organization"], "schema:name": "Banco Central de Chile"},
                ]
            },
            "schema:publisher": {"@type": ["schema:Organization"], "schema:name": "INE"},
            "schema:datePublished": "2021-05-10",
        }
        snapshot = repr(fields)
        events = check_grounding(fields, SOURCE)
        assert [(e.field, e.location, e.value, e.action) for e in events] == [
            ("schema:creator", "schema:creator[1]", "Banco Central de Chile", "flagged")
        ]
        assert repr(fields) == snapshot

    def test_role_wrapped_contributor_and_affiliation(self) -> None:
        fields = {
            "schema:contributor": [
                {
                    "@type": ["schema:Role"],
                    "schema:roleName": "Producer",
                    "schema:contributor": {
                        "@type": ["schema:Person"],
                        "schema:name": "Ana Pérez",
                        "schema:affiliation": [
                            {"@type": ["schema:Organization"], "schema:name": "Universidad de Concepción"},
                            {"@type": ["schema:Organization"], "schema:name": "Banco Central de Chile"},
                        ],
                    },
                }
            ]
        }
        events = check_grounding(fields, SOURCE)
        locations = {e.location for e in events}
        assert "schema:contributor[0].schema:affiliation[1]" in locations
        assert "schema:contributor[0].schema:affiliation[0]" not in locations

    def test_funding_award_and_funder(self) -> None:
        fields = {
            "schema:funding": [
                {
                    "@type": ["schema:MonetaryGrant"],
                    "schema:funder": {"@type": ["schema:Organization"], "schema:name": "ANID"},
                    "schema:identifier": {"schema:propertyID": "award", "schema:value": "9999999"},
                }
            ]
        }
        events = check_grounding(fields, SOURCE)
        assert [e.location for e in events] == ["schema:funding[0].schema:identifier"]

    def test_date_modified_and_copyright_holder_are_not_checked(self) -> None:
        fields = {"schema:dateModified": "2031-01-01", "schema:copyrightHolder": "Estado de Chile"}
        assert check_grounding(fields, SOURCE) == []

    def test_empty_document(self) -> None:
        assert check_grounding({}, SOURCE) == []


def test_repair_mojibake_fixes_double_encoding_and_leaves_other_text_alone() -> None:
    from metadata_enricher.enrichers.grounding import repair_mojibake

    assert repair_mojibake("KÃ¶ppen") == "Köppen"
    assert repair_mojibake("Köppen") == "Köppen"
    assert repair_mojibake("Ã plain — dash") == "Ã plain — dash"  # not a lossless round trip
