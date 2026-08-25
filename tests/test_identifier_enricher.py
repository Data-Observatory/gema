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


def _mock_isni_only_resolver(isni_id: str = "000000040628717X") -> MagicMock:
    """A resolver whose match fell back to ISNI SRU — no ROR hit at all."""
    resolver = MagicMock()
    resolver.resolve.return_value = IdentifierMatch(
        ror_id=None,
        isni_id=isni_id,
        org_name="Test Org",
        confidence=0.95,
        matched_via="isni_sru",
        status="auto",
    )
    return resolver


def _doc_with_fields(fields: dict) -> MetadataDocument:
    doc = MetadataDocument()
    for k, v in fields.items():
        doc.set_field(k, v)
    return doc


# --------------------------------------------------------------------------


class TestEnrichCreators:
    """IdentifierEnricher: creator name_identifiers resolution."""

    def test_organizational_creator_gets_all_found_identifiers(self) -> None:
        """A match carrying both ROR and ISNI writes BOTH — not just one preferred scheme."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name": "Ministerio de Hacienda", "creator_name_type": "Organizational", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        identifiers = doc.get_field("creators")[0]["name_identifiers"]
        assert len(identifiers) == 2
        assert identifiers[0]["name_identifier"] == "https://ror.org/01h6h5x94"
        assert identifiers[0]["name_identifier_scheme"] == "ROR"
        assert identifiers[1]["name_identifier"] == "000000040628717X"
        assert identifiers[1]["name_identifier_scheme"] == "ISNI"

    def test_personal_creator_without_name_split_not_resolved(self) -> None:
        """No given_name/family_name split — nothing to search ORCID with."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name": "John Doe", "creator_name_type": "Personal", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["name_identifiers"] == []
        resolver.resolve.assert_not_called()
        resolver.resolve_person.assert_not_called()

    def test_personal_creator_unambiguous_orcid_match_written(self) -> None:
        resolver = _mock_resolver()
        resolver.resolve_person.return_value = IdentifierMatch(
            orcid_id="0000-0002-1825-0097",
            org_name="Jane Roe",
            confidence=1.0,
            matched_via="orcid_search",
            status="auto",
        )
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{
                "creator_name": "Jane Roe",
                "creator_name_type": "Personal",
                "given_name": "Jane",
                "family_name": "Roe",
                "name_identifiers": [],
            }]
        })
        enricher.enrich(doc)
        identifiers = doc.get_field("creators")[0]["name_identifiers"]
        resolver.resolve_person.assert_called_once_with("Jane", "Roe", None)
        assert len(identifiers) == 1
        assert identifiers[0]["name_identifier"] == "https://orcid.org/0000-0002-1825-0097"
        assert identifiers[0]["name_identifier_scheme"] == "ORCID"

    def test_personal_creator_passes_affiliation_to_orcid_search(self) -> None:
        resolver = _mock_resolver()
        resolver.resolve_person.return_value = None
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{
                "creator_name": "Jane Roe",
                "creator_name_type": "Personal",
                "given_name": "Jane",
                "family_name": "Roe",
                "affiliations": [{"affiliation": "Universidad de Chile"}],
                "name_identifiers": [],
            }]
        })
        enricher.enrich(doc)
        resolver.resolve_person.assert_called_once_with("Jane", "Roe", "Universidad de Chile")

    def test_personal_creator_ambiguous_orcid_match_not_written(self) -> None:
        resolver = _mock_resolver()
        resolver.resolve_person.return_value = IdentifierMatch(
            orcid_id="0000-0002-1825-0097",
            org_name="Jane Roe",
            confidence=0.5,
            matched_via="orcid_search",
            status="review",
        )
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{
                "creator_name": "Jane Roe",
                "creator_name_type": "Personal",
                "given_name": "Jane",
                "family_name": "Roe",
                "name_identifiers": [],
            }]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["name_identifiers"] == []

    def test_personal_creator_with_existing_identifier_not_reresolved(self) -> None:
        resolver = _mock_resolver()
        existing = [{"name_identifier": "https://orcid.org/EXISTING", "name_identifier_scheme": "ORCID"}]
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{
                "creator_name": "Jane Roe",
                "creator_name_type": "Personal",
                "given_name": "Jane",
                "family_name": "Roe",
                "name_identifiers": existing,
            }]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["name_identifiers"] == existing
        resolver.resolve_person.assert_not_called()

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

    def test_isni_only_match_still_written(self) -> None:
        """When the resolver falls back to ISNI (no ROR hit), that ISNI must
        land on the document — not be silently dropped."""
        resolver = _mock_isni_only_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name": "Test Org", "creator_name_type": "Organizational", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        identifiers = doc.get_field("creators")[0]["name_identifiers"]
        assert len(identifiers) == 1
        assert identifiers[0]["name_identifier"] == "000000040628717X"
        assert identifiers[0]["name_identifier_scheme"] == "ISNI"
        assert identifiers[0]["scheme_uri"] == "https://isni.org"

    def test_affiliation_isni_only_match_still_written(self) -> None:
        resolver = _mock_isni_only_resolver()
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
        assert affil["affiliation_identifier"] == "000000040628717X"
        assert affil["affiliation_identifier_scheme"] == "ISNI"

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

    def test_publisher_isni_only_match_still_written(self) -> None:
        resolver = _mock_isni_only_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "publishers": [{"publisher_name": "Ministerio", "publisher_identifier": ""}]
        })
        enricher.enrich(doc)
        pub = doc.get_field("publishers")[0]
        assert pub["publisher_identifier"] == "000000040628717X"
        assert pub["publisher_identifier_scheme"] == "ISNI"
        assert pub["publisher_scheme_uri"] == "https://isni.org"

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

    def test_funder_gets_all_found_identifiers(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "funding_references": [{"funder_name": "ANID", "funder_identifiers": []}]
        })
        enricher.enrich(doc)
        ref = doc.get_field("funding_references")[0]
        assert len(ref["funder_identifiers"]) == 2
        assert ref["funder_identifiers"][0]["funder_identifier"] == "https://ror.org/01h6h5x94"
        assert ref["funder_identifiers"][1]["funder_identifier"] == "000000040628717X"
        assert ref["funder_identifiers"][1]["funder_identifier_type"] == "ISNI"

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

    def test_funder_isni_only_match_still_written(self) -> None:
        resolver = _mock_isni_only_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "funding_references": [{"funder_name": "ANID", "funder_identifiers": []}]
        })
        enricher.enrich(doc)
        ref = doc.get_field("funding_references")[0]
        assert ref["funder_identifiers"][0]["funder_identifier"] == "000000040628717X"
        assert ref["funder_identifiers"][0]["funder_identifier_type"] == "ISNI"

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
        """No 'creators' field at all — must not crash, and must not stop
        the empty 'publishers' list from being handled too."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": []})
        result = enricher.enrich(doc)
        assert result is doc
        assert doc.get_field("creators") is None
        assert doc.get_field("publishers") == []
        resolver.resolve.assert_not_called()

    def test_creator_without_name_skipped(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [{"creator_name_type": "Organizational", "name_identifiers": []}]
        })
        enricher.enrich(doc)
        resolver.resolve.assert_not_called()


# --------------------------------------------------------------------------


class TestCountryPassthrough:
    """IdentifierEnricher: the optional country hint reaches every resolve() call."""

    def test_country_forwarded_for_organizational_creator(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [
                {
                    "creator_name": "Ministerio de Hacienda",
                    "creator_name_type": "Organizational",
                    "name_identifiers": [],
                }
            ]
        })
        enricher.enrich(doc, country="CL")
        resolver.resolve.assert_called_once_with("Ministerio de Hacienda", "CL")

    def test_country_forwarded_for_affiliation(self) -> None:
        """Affiliation resolution only runs for Organizational creators —
        a Personal creator's ``continue`` (see ``_enrich_creators``) skips
        the affiliations block entirely, so an Organizational creator with
        an already-set name identifier isolates just the affiliation call."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [
                {
                    "creator_name": "Some Org",
                    "creator_name_type": "Organizational",
                    "name_identifiers": [{"name_identifier": "already-set"}],
                    "affiliations": [{"affiliation": "Universidad de Chile"}],
                }
            ]
        })
        enricher.enrich(doc, country="CL")
        resolver.resolve.assert_called_once_with("Universidad de Chile", "CL")

    def test_country_forwarded_for_publisher(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": [{"publisher_name": "Some Publisher"}]})
        enricher.enrich(doc, country="AR")
        resolver.resolve.assert_called_once_with("Some Publisher", "AR")

    def test_country_forwarded_for_funder(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "funding_references": [{"funder_name": "Some Funder", "funder_identifiers": []}]
        })
        enricher.enrich(doc, country="AR")
        resolver.resolve.assert_called_once_with("Some Funder", "AR")

    def test_no_country_defaults_to_none(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": [{"publisher_name": "Some Publisher"}]})
        enricher.enrich(doc)
        resolver.resolve.assert_called_once_with("Some Publisher", None)


# --------------------------------------------------------------------------


class TestProvenance:
    """IdentifierEnricher: every attached identifier carries match provenance."""

    def test_name_identifiers_carry_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [
                {
                    "creator_name": "Ministerio de Hacienda",
                    "creator_name_type": "Organizational",
                    "name_identifiers": [],
                }
            ]
        })
        enricher.enrich(doc)
        entry = doc.get_field("creators")[0]["name_identifiers"][0]
        assert entry["matched_via"] == "ror_affiliation"
        assert entry["confidence"] == 0.95
        assert entry["status"] == "auto"

    def test_funder_identifiers_carry_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "funding_references": [{"funder_name": "Some Funder", "funder_identifiers": []}]
        })
        enricher.enrich(doc)
        entry = doc.get_field("funding_references")[0]["funder_identifiers"][0]
        assert entry["matched_via"] == "ror_affiliation"
        assert entry["confidence"] == 0.95
        assert entry["status"] == "auto"

    def test_affiliation_identifier_carries_prefixed_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [
                {
                    "creator_name": "Some Org",
                    "creator_name_type": "Organizational",
                    "name_identifiers": [{"name_identifier": "already-set"}],
                    "affiliations": [{"affiliation": "Universidad de Chile"}],
                }
            ]
        })
        enricher.enrich(doc)
        affil = doc.get_field("creators")[0]["affiliations"][0]
        assert affil["affiliation_identifier_matched_via"] == "ror_affiliation"
        assert affil["affiliation_identifier_confidence"] == 0.95
        assert affil["affiliation_identifier_status"] == "auto"

    def test_publisher_identifier_carries_prefixed_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": [{"publisher_name": "Some Publisher"}]})
        enricher.enrich(doc)
        publisher = doc.get_field("publishers")[0]
        assert publisher["publisher_identifier_matched_via"] == "ror_affiliation"
        assert publisher["publisher_identifier_confidence"] == 0.95
        assert publisher["publisher_identifier_status"] == "auto"

    def test_orcid_name_identifier_carries_provenance(self) -> None:
        resolver = MagicMock()
        resolver.resolve_person.return_value = IdentifierMatch(
            orcid_id="0000-0002-1825-0097",
            org_name="Jane Roe",
            confidence=1.0,
            matched_via="orcid_search",
            status="auto",
        )
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [
                {
                    "creator_name": "Roe, Jane",
                    "creator_name_type": "Personal",
                    "given_name": "Jane",
                    "family_name": "Roe",
                    "name_identifiers": [],
                }
            ]
        })
        enricher.enrich(doc)
        entry = doc.get_field("creators")[0]["name_identifiers"][0]
        assert entry["matched_via"] == "orcid_search"
        assert entry["confidence"] == 1.0
        assert entry["status"] == "auto"

    def test_override_provenance_flows_through_unchanged(self) -> None:
        """Provenance isn't special-cased for overrides -- resolve() already
        returns matched_via='override' transparently, and it's threaded
        through exactly like any other match."""
        resolver = MagicMock()
        resolver.resolve.return_value = IdentifierMatch(
            ror_id="https://ror.org/curated",
            org_name="Some Publisher",
            confidence=1.0,
            matched_via="override",
            status="auto",
        )
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": [{"publisher_name": "Some Publisher"}]})
        enricher.enrich(doc)
        publisher = doc.get_field("publishers")[0]
        assert publisher["publisher_identifier_matched_via"] == "override"

    def test_review_status_org_match_is_not_auto_attached(self) -> None:
        """Deliberate behavior change (2026-08-25, code review follow-up):
        org identifiers (ROR/ISNI) now get the same status=="auto" gate
        ORCID already had -- a wrong PID is worse than a missing one, so an
        ambiguous match is logged, not attached, for orgs too."""
        resolver = MagicMock()
        resolver.resolve.return_value = IdentifierMatch(
            ror_id="https://ror.org/ambiguous",
            org_name="Some Org",
            confidence=0.5,
            matched_via="ror_query_fuzzy",
            status="review",
        )
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [
                {"creator_name": "Some Org", "creator_name_type": "Organizational", "name_identifiers": []}
            ]
        })
        enricher.enrich(doc)
        assert doc.get_field("creators")[0]["name_identifiers"] == []


# --------------------------------------------------------------------------


def _review_resolver(ror_id: str = "https://ror.org/ambiguous") -> MagicMock:
    resolver = MagicMock()
    resolver.resolve.return_value = IdentifierMatch(
        ror_id=ror_id,
        org_name="Some Org",
        confidence=0.5,
        matched_via="ror_query_fuzzy",
        status="review",
    )
    return resolver


class TestStatusGatingAllPaths:
    """IdentifierEnricher: status=="auto" gate applies to every org-identifier path."""

    def test_affiliation_identifier_not_attached_when_review(self) -> None:
        resolver = _review_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "creators": [
                {
                    "creator_name": "Some Org",
                    "creator_name_type": "Organizational",
                    "name_identifiers": [{"name_identifier": "already-set"}],
                    "affiliations": [{"affiliation": "Universidad de Chile"}],
                }
            ]
        })
        enricher.enrich(doc)
        affil = doc.get_field("creators")[0]["affiliations"][0]
        assert "affiliation_identifier" not in affil
        assert "affiliation_identifier_matched_via" not in affil

    def test_publisher_identifier_not_attached_when_review(self) -> None:
        resolver = _review_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": [{"publisher_name": "Some Publisher"}]})
        enricher.enrich(doc)
        publisher = doc.get_field("publishers")[0]
        assert publisher.get("publisher_identifier") is None
        assert "publisher_identifier_matched_via" not in publisher

    def test_funder_identifiers_not_attached_when_review(self) -> None:
        resolver = _review_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({
            "funding_references": [{"funder_name": "Some Funder", "funder_identifiers": []}]
        })
        enricher.enrich(doc)
        assert doc.get_field("funding_references")[0]["funder_identifiers"] == []

    def test_auto_status_still_attaches_normally(self) -> None:
        """Control: the existing 'auto' fixture (_mock_resolver) still works
        unchanged -- this gate only rejects 'review'/'nomatch', not 'auto'."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"publishers": [{"publisher_name": "Some Publisher"}]})
        enricher.enrich(doc)
        publisher = doc.get_field("publishers")[0]
        assert publisher["publisher_identifier"] == "https://ror.org/01h6h5x94"
