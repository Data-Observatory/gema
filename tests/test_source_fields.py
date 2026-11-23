"""Tests for enrichers/source_fields.py."""

from __future__ import annotations

from metadata_enricher.enrichers.source_fields import enforce_source_fields
from metadata_enricher.types import MetadataDocument, ResourceDescription

RESOURCE = ResourceDescription(
    title="Gastos municipales / Municipal expenses",
    description="Serie mensual de gastos.",
)


def _doc(**fields: str | list[str]) -> MetadataDocument:
    return MetadataDocument(fields=dict(fields))


def test_exact_copy_is_left_alone() -> None:
    doc = _doc(**{"schema:name": RESOURCE.title, "schema:description": RESOURCE.description})
    assert enforce_source_fields(doc, RESOURCE) == []


def test_bilingual_title_split_is_a_valid_subform() -> None:
    # The prompt lets the model keep the main form in schema:name and move the other to sameAs.
    doc = _doc(**{"schema:name": "Gastos municipales", "schema:description": RESOURCE.description})
    assert enforce_source_fields(doc, RESOURCE) == []
    assert doc.get_field("schema:name") == "Gastos municipales"


def test_accent_case_and_punctuation_differences_are_left_alone() -> None:
    resource = ResourceDescription(title="Encuesta de Presupuestos Familiares (EPF)")
    doc = _doc(**{"schema:name": "encuesta de presupuestos familiares EPF"})
    assert enforce_source_fields(doc, resource) == []


def test_empty_is_filled() -> None:
    doc = _doc(**{"schema:name": ""})
    events = enforce_source_fields(doc, RESOURCE)
    assert doc.get_field("schema:name") == RESOURCE.title
    assert doc.get_field("schema:description") == RESOURCE.description
    assert {(e.field, e.action) for e in events} == {
        ("schema:name", "filled"),
        ("schema:description", "filled"),
    }


def test_paraphrase_is_overridden_and_reported() -> None:
    doc = _doc(**{"schema:name": "Municipal spending dataset", "schema:description": "x"})
    events = enforce_source_fields(doc, RESOURCE)
    assert doc.get_field("schema:name") == RESOURCE.title
    assert {(e.field, e.action, e.value) for e in events} == {
        ("schema:name", "overridden", "Municipal spending dataset"),
        ("schema:description", "overridden", "x"),
    }


def test_no_source_value_means_no_action() -> None:
    doc = _doc(**{"schema:name": "Whatever the model said"})
    assert enforce_source_fields(doc, ResourceDescription(title="   ")) == []
    assert doc.get_field("schema:name") == "Whatever the model said"


def test_model_repaired_mojibake_in_source_is_not_overridden() -> None:
    # Source arrived double-encoded ("KÃ¶ppen"); the model fixed it. Overriding
    # would reintroduce the damage.
    resource = ResourceDescription(description="Clasificacion de KÃ¶ppen-Geiger en espaÃ±ol")
    doc = _doc(**{"schema:description": "Clasificacion de Köppen-Geiger en español"})
    assert enforce_source_fields(doc, resource) == []
    assert doc.get_field("schema:description") == "Clasificacion de Köppen-Geiger en español"


def test_empty_is_filled_with_repaired_source_when_mojibake() -> None:
    resource = ResourceDescription(description="espaÃ±ol")
    doc = _doc()
    enforce_source_fields(doc, resource)
    assert doc.get_field("schema:description") == "español"
