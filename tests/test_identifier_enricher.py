"""Tests for enrichers.identifier_enricher."""

from __future__ import annotations

from unittest.mock import MagicMock

from metadata_enricher.enrichers.identifier_enricher import IdentifierEnricher
from metadata_enricher.enrichers.identifier_types import IdentifierMatch
from metadata_enricher.types import MetadataDocument


def _mock_resolver(ror_id: str | None = "https://ror.org/01h6h5x94") -> MagicMock:
    resolver = MagicMock()
    if ror_id:
        resolver.resolve.return_value = IdentifierMatch(
            ror_id=ror_id,
            isni_id="000000040628717X",
            org_name="Test Org",
            confidence=0.95,
            matched_via="ror_affiliation",
            status="auto",
        )
    else:
        resolver.resolve.return_value = None
    return resolver


def _doc_with_fields(fields: dict) -> MetadataDocument:
    doc = MetadataDocument()
    for k, v in fields.items():
        doc.set_field(k, v)
    return doc


# --------------------------------------------------------------------------


class TestEnrichCreators:
    """IdentifierEnricher: creator name_identifiers resolution."""

    def test_organizational_creator_gets_name_identifier(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name": "Ministerio de Hacienda", "creator_name_type": "Organizational", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        identifiers = doc.get_field("creators")[0]["name_identifiers"]
        assert len(identifiers) == 1
        assert identifiers[0]["name_identifier"] == "https://ror.org/01h6h5x94"
        assert identifiers[0]["name_identifier_scheme"] == "ROR"

    def test_personal_creator_skipped(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name": "John Doe", "creator_name_type": "Personal", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["name_identifiers"] == []
        resolver.resolve.assert_not_called()

    def test_already_populated_name_identifiers_preserved(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        existing = [{"name_identifier": "https://ror.org/EXISTING", "name_identifier_scheme": "ROR"}]
        doc = _doc_with_fields({
            "creators": [{"creator_name": "Test", "creator_name_type": "Organizational", "name_identifiers": existing}]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["name_identifiers"] == existing

    def test_blank_placeholder_name_identifiers_still_enriched(self) -> None:
        """LLM sometimes emits a non-empty list of all-blank-string dicts
        instead of []. That must not read as 'already has an identifier'.
        """
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{
                "creator_name": "Ministerio del Medio Ambiente",
                "creator_name_type": "Organizational",
                "name_identifiers": [
                    {"name_identifier": "", "name_identifier_scheme": "", "scheme_uri": ""}
                ],
            }]
        })
        enricher.enrich(doc)
        identifiers = doc.get_field("creators")[0]["name_identifiers"]
        assert identifiers[0]["name_identifier"] == "https://ror.org/01h6h5x94"

    def test_resolver_returns_none_leaves_empty(self) -> None:
        resolver = _mock_resolver(ror_id=None)
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name": "Unknown", "creator_name_type": "Organizational", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["name_identifiers"] == []

    def test_affiliation_gets_identifier(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{
                "creator_name": "Test Org",
                "creator_name_type": "Organizational",
                "name_identifiers": [{"name_identifier": "exists"}],
                "affiliations": [{"affiliation": "Parent Org", "affiliation_identifier": ""}],
            }]
        })
        enricher.enrich(doc)
        affil = doc.get_field("creators")[0]["affiliations"][0]
        assert affil["affiliation_identifier"] == "https://ror.org/01h6h5x94"

    def test_affiliation_already_populated_preserved(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{
                "creator_name": "Test",
                "creator_name_type": "Organizational",
                "name_identifiers": [{"name_identifier": "exists"}],
                "affiliations": [{"affiliation": "Parent", "affiliation_identifier": "EXISTING"}],
            }]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["affiliations"][0]["affiliation_identifier"] == "EXISTING"


# --------------------------------------------------------------------------


class TestEnrichPublishers:
    """IdentifierEnricher: publisher_identifier resolution."""

    def test_publisher_gets_identifier(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "publishers": [{"publisher_name": "Ministerio", "publisher_identifier": ""}]
        })
        enricher.enrich(doc)
        pub = doc.get_field("publishers")[0]
        assert pub["publisher_identifier"] == "https://ror.org/01h6h5x94"
        assert pub["publisher_identifier_scheme"] == "ROR"

    def test_publisher_already_populated_preserved(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "publishers": [{"publisher_name": "Test", "publisher_identifier": "EXISTING"}]
        })
        enricher.enrich(doc)
        assert doc.get_field("publishers")[0]["publisher_identifier"] == "EXISTING"


# --------------------------------------------------------------------------


class TestEnrichFundingReferences:
    """IdentifierEnricher: funder_identifiers resolution."""

    def test_funder_gets_identifiers(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "funding_references": [{"funder_name": "ANID", "funder_identifiers": []}]
        })
        enricher.enrich(doc)
        ref = doc.get_field("funding_references")[0]
        assert len(ref["funder_identifiers"]) == 1
        assert ref["funder_identifiers"][0]["funder_identifier"] == "https://ror.org/01h6h5x94"

    def test_blank_placeholder_funder_identifiers_still_enriched(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "funding_references": [{
                "funder_name": "ANID",
                "funder_identifiers": [{"funder_identifier": "", "funder_identifier_type": ""}],
            }]
        })
        enricher.enrich(doc)
        ref = doc.get_field("funding_references")[0]
        assert ref["funder_identifiers"][0]["funder_identifier"] == "https://ror.org/01h6h5x94"

    def test_funder_already_populated_preserved(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        existing = [{"funder_identifier": "EXISTING"}]
        doc = _doc_with_fields({
            "funding_references": [{"funder_name": "ANID", "funder_identifiers": existing}]
        })
        enricher.enrich(doc)
        assert doc.get_field("funding_references")[0]["funder_identifiers"] == existing


# --------------------------------------------------------------------------


class TestEnrichEdgeCases:
    """IdentifierEnricher: edge cases and robustness."""

    def test_empty_document_no_crash(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = MetadataDocument()
        enricher.enrich(doc)
        resolver.resolve.assert_not_called()

    def test_no_creators_key(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": []})
        enricher.enrich(doc)

    def test_creator_without_name_skipped(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name_type": "Organizational", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        resolver.resolve.assert_not_called()
