"""Tests for enrichers.identifier_enricher (CDIF field names)."""

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


def _org(name: str, identifiers: list | None = None, affiliations: list | None = None) -> dict:
    entry = {"@type": ["schema:Organization"], "schema:name": name, "schema:identifier": identifiers or []}
    if affiliations is not None:
        entry["schema:affiliation"] = affiliations
    return entry


def _person(
    name: str, given: str, family: str, identifiers: list | None = None, affiliations=None
) -> dict:
    entry = {
        "@type": ["schema:Person"],
        "schema:name": name,
        "schema:givenName": given,
        "schema:familyName": family,
        "schema:identifier": identifiers or [],
    }
    if affiliations is not None:
        entry["schema:affiliation"] = affiliations
    return entry


# --------------------------------------------------------------------------


class TestEnrichCreators:
    """IdentifierEnricher: schema:creator identifier resolution."""

    def test_organizational_creator_gets_all_found_identifiers(self) -> None:
        """A match carrying both ROR and ISNI writes BOTH — not just one preferred scheme."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:creator": [_org("Ministerio de Hacienda")]})
        enricher.enrich(doc)
        identifiers = doc.get_field("schema:creator")[0]["schema:identifier"]
        assert len(identifiers) == 2
        assert identifiers[0]["schema:value"] == "https://ror.org/01h6h5x94"
        assert identifiers[0]["schema:propertyID"] == "ROR"
        # Regression: ROR's own API returns "id" as an already-full URI --
        # unconditionally prefixing it produced doubled URLs
        # ("https://ror.org/https://ror.org/...") in real recorded output
        # (8 occurrences across 4 committed golden fixtures, found by
        # review). schema:value and schema:url must match exactly here,
        # not accumulate a second prefix.
        assert identifiers[0]["schema:url"] == "https://ror.org/01h6h5x94"
        assert identifiers[1]["schema:value"] == "000000040628717X"
        assert identifiers[1]["schema:propertyID"] == "ISNI"
        assert identifiers[1]["schema:url"] == "https://isni.org/000000040628717X"

    def test_wrapped_jsonld_list_creator_is_enriched_in_place(self) -> None:
        """schema:creator arrives as {"@list": [...]} once a real pipeline
        run has gone through CDIFDiscoveryProfile.merge_agent_results
        (constraint C4) -- the enricher must unwrap to reach entries, and
        mutations must land back in the same wrapped document field."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:creator": {"@list": [_org("Ministerio de Hacienda")]}})
        enricher.enrich(doc)
        wrapped = doc.get_field("schema:creator")
        assert isinstance(wrapped, dict) and "@list" in wrapped
        identifiers = wrapped["@list"][0]["schema:identifier"]
        assert identifiers[0]["schema:propertyID"] == "ROR"

    def test_personal_creator_without_name_split_not_resolved(self) -> None:
        """No given_name/family_name split — nothing to search ORCID with."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:creator": [{"@type": ["schema:Person"], "schema:name": "John Doe", "schema:identifier": []}]}
        )
        enricher.enrich(doc)
        assert doc.get_field("schema:creator")[0]["schema:identifier"] == []
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
        doc = _doc_with_fields({"schema:creator": [_person("Jane Roe", "Jane", "Roe")]})
        enricher.enrich(doc)
        identifiers = doc.get_field("schema:creator")[0]["schema:identifier"]
        resolver.resolve_person.assert_called_once_with("Jane", "Roe", None)
        assert len(identifiers) == 1
        assert identifiers[0]["schema:value"] == "0000-0002-1825-0097"
        assert identifiers[0]["schema:propertyID"] == "ORCID"

    def test_personal_creator_passes_affiliation_to_orcid_search(self) -> None:
        resolver = _mock_resolver()
        resolver.resolve_person.return_value = None
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _person(
                        "Jane Roe",
                        "Jane",
                        "Roe",
                        affiliations=[_org("Universidad de Chile")],
                    )
                ]
            }
        )
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
        doc = _doc_with_fields({"schema:creator": [_person("Jane Roe", "Jane", "Roe")]})
        enricher.enrich(doc)
        assert doc.get_field("schema:creator")[0]["schema:identifier"] == []

    def test_personal_creator_with_existing_identifier_not_reresolved(self) -> None:
        resolver = _mock_resolver()
        existing = [{"schema:propertyID": "ORCID", "schema:value": "EXISTING"}]
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:creator": [_person("Jane Roe", "Jane", "Roe", identifiers=existing)]}
        )
        enricher.enrich(doc)
        assert doc.get_field("schema:creator")[0]["schema:identifier"] == existing
        resolver.resolve_person.assert_not_called()

    def test_already_populated_identifiers_preserved(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        existing = [{"schema:propertyID": "ROR", "schema:value": "https://ror.org/EXISTING"}]
        doc = _doc_with_fields({"schema:creator": [_org("Test", identifiers=existing)]})
        enricher.enrich(doc)
        assert doc.get_field("schema:creator")[0]["schema:identifier"] == existing

    def test_blank_placeholder_identifiers_still_enriched(self) -> None:
        """LLM sometimes emits a non-empty list of all-blank-string dicts
        instead of []. That must not read as 'already has an identifier'."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _org(
                        "Ministerio del Medio Ambiente",
                        identifiers=[{"schema:propertyID": "", "schema:value": "", "schema:url": ""}],
                    )
                ]
            }
        )
        enricher.enrich(doc)
        identifiers = doc.get_field("schema:creator")[0]["schema:identifier"]
        assert identifiers[0]["schema:value"] == "https://ror.org/01h6h5x94"

    def test_isni_only_match_still_written(self) -> None:
        """When the resolver falls back to ISNI (no ROR hit), that ISNI must
        land on the document — not be silently dropped."""
        resolver = _mock_isni_only_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:creator": [_org("Test Org")]})
        enricher.enrich(doc)
        identifiers = doc.get_field("schema:creator")[0]["schema:identifier"]
        assert len(identifiers) == 1
        assert identifiers[0]["schema:value"] == "000000040628717X"
        assert identifiers[0]["schema:propertyID"] == "ISNI"
        assert identifiers[0]["schema:url"] == "https://isni.org/000000040628717X"

    def test_affiliation_isni_only_match_still_written(self) -> None:
        resolver = _mock_isni_only_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _org(
                        "Test Org",
                        identifiers=[{"schema:propertyID": "ROR", "schema:value": "exists"}],
                        affiliations=[_org("Parent Org")],
                    )
                ]
            }
        )
        enricher.enrich(doc)
        affil = doc.get_field("schema:creator")[0]["schema:affiliation"][0]
        assert affil["schema:identifier"][0]["schema:value"] == "000000040628717X"
        assert affil["schema:identifier"][0]["schema:propertyID"] == "ISNI"

    def test_resolver_returns_none_leaves_empty(self) -> None:
        resolver = _mock_resolver(ror_id=None)
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:creator": [_org("Unknown")]})
        enricher.enrich(doc)
        assert doc.get_field("schema:creator")[0]["schema:identifier"] == []

    def test_affiliation_gets_identifier(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _org(
                        "Test Org",
                        identifiers=[{"schema:propertyID": "ROR", "schema:value": "exists"}],
                        affiliations=[_org("Parent Org")],
                    )
                ]
            }
        )
        enricher.enrich(doc)
        affil = doc.get_field("schema:creator")[0]["schema:affiliation"][0]
        assert affil["schema:identifier"][0]["schema:value"] == "https://ror.org/01h6h5x94"

    def test_affiliation_already_populated_preserved(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        existing = [{"schema:propertyID": "ROR", "schema:value": "EXISTING"}]
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _org(
                        "Test",
                        identifiers=[{"schema:propertyID": "ROR", "schema:value": "exists"}],
                        affiliations=[_org("Parent", identifiers=existing)],
                    )
                ]
            }
        )
        enricher.enrich(doc)
        affil = doc.get_field("schema:creator")[0]["schema:affiliation"][0]
        assert affil["schema:identifier"] == existing


# --------------------------------------------------------------------------


class TestEnrichPublisher:
    """IdentifierEnricher: schema:publisher identifier resolution."""

    def test_publisher_gets_identifier(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": _org("Ministerio")})
        enricher.enrich(doc)
        pub = doc.get_field("schema:publisher")
        assert pub["schema:identifier"][0]["schema:value"] == "https://ror.org/01h6h5x94"
        assert pub["schema:identifier"][0]["schema:propertyID"] == "ROR"
        # Regression: _enrich_publisher was the one of three ROR-URL-writing
        # sites that got missed when _scheme_url() was introduced elsewhere
        # in this module -- schema:url must equal schema:value exactly, not
        # accumulate a second "https://ror.org/" prefix.
        assert pub["schema:identifier"][0]["schema:url"] == "https://ror.org/01h6h5x94"

    def test_publisher_isni_only_match_still_written(self) -> None:
        resolver = _mock_isni_only_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": _org("Ministerio")})
        enricher.enrich(doc)
        pub = doc.get_field("schema:publisher")
        assert pub["schema:identifier"][0]["schema:value"] == "000000040628717X"
        assert pub["schema:identifier"][0]["schema:propertyID"] == "ISNI"

    def test_publisher_already_populated_preserved(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        existing = [{"schema:propertyID": "ROR", "schema:value": "EXISTING"}]
        doc = _doc_with_fields({"schema:publisher": _org("Test", identifiers=existing)})
        enricher.enrich(doc)
        assert doc.get_field("schema:publisher")["schema:identifier"] == existing


# --------------------------------------------------------------------------


class TestEnrichFunding:
    """IdentifierEnricher: schema:funding funder identifier resolution."""

    def test_funder_gets_all_found_identifiers(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:funding": [{"@type": ["schema:MonetaryGrant"], "schema:funder": _org("ANID")}]}
        )
        enricher.enrich(doc)
        funder = doc.get_field("schema:funding")[0]["schema:funder"]
        assert len(funder["schema:identifier"]) == 2
        assert funder["schema:identifier"][0]["schema:value"] == "https://ror.org/01h6h5x94"
        assert funder["schema:identifier"][1]["schema:value"] == "000000040628717X"
        assert funder["schema:identifier"][1]["schema:propertyID"] == "ISNI"

    def test_blank_placeholder_funder_identifiers_still_enriched(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:funding": [
                    {
                        "@type": ["schema:MonetaryGrant"],
                        "schema:funder": _org("ANID", identifiers=[{"schema:propertyID": "", "schema:value": ""}]),
                    }
                ]
            }
        )
        enricher.enrich(doc)
        funder = doc.get_field("schema:funding")[0]["schema:funder"]
        assert funder["schema:identifier"][0]["schema:value"] == "https://ror.org/01h6h5x94"

    def test_funder_isni_only_match_still_written(self) -> None:
        resolver = _mock_isni_only_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:funding": [{"@type": ["schema:MonetaryGrant"], "schema:funder": _org("ANID")}]}
        )
        enricher.enrich(doc)
        funder = doc.get_field("schema:funding")[0]["schema:funder"]
        assert funder["schema:identifier"][0]["schema:value"] == "000000040628717X"
        assert funder["schema:identifier"][0]["schema:propertyID"] == "ISNI"

    def test_funder_already_populated_preserved(self) -> None:
        resolver = _mock_resolver()
        existing = [{"schema:propertyID": "ROR", "schema:value": "EXISTING"}]
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:funding": [
                    {"@type": ["schema:MonetaryGrant"], "schema:funder": _org("ANID", identifiers=existing)}
                ]
            }
        )
        enricher.enrich(doc)
        assert doc.get_field("schema:funding")[0]["schema:funder"]["schema:identifier"] == existing


# --------------------------------------------------------------------------


class TestEnrichEdgeCases:
    """IdentifierEnricher: edge cases and robustness."""

    def test_empty_document_no_crash(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = MetadataDocument()
        enricher.enrich(doc)
        resolver.resolve.assert_not_called()

    def test_no_creator_key(self) -> None:
        """No 'schema:creator' field at all — must not crash, and must not
        stop schema:publisher from being handled too."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": {}})
        result = enricher.enrich(doc)
        assert result is doc
        assert doc.get_field("schema:creator") is None
        resolver.resolve.assert_not_called()

    def test_creator_without_name_skipped(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:creator": [{"@type": ["schema:Organization"], "schema:identifier": []}]}
        )
        enricher.enrich(doc)
        resolver.resolve.assert_not_called()


# --------------------------------------------------------------------------


class TestCountryPassthrough:
    """IdentifierEnricher: the optional country hint reaches every resolve() call."""

    def test_country_forwarded_for_organizational_creator(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:creator": [_org("Ministerio de Hacienda")]})
        enricher.enrich(doc, country="CL")
        resolver.resolve.assert_called_once_with("Ministerio de Hacienda", "CL")

    def test_country_forwarded_for_affiliation(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _org(
                        "Some Org",
                        identifiers=[{"schema:propertyID": "ROR", "schema:value": "already-set"}],
                        affiliations=[_org("Universidad de Chile")],
                    )
                ]
            }
        )
        enricher.enrich(doc, country="CL")
        resolver.resolve.assert_called_once_with("Universidad de Chile", "CL")

    def test_country_forwarded_for_publisher(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": _org("Some Publisher")})
        enricher.enrich(doc, country="AR")
        resolver.resolve.assert_called_once_with("Some Publisher", "AR")

    def test_country_forwarded_for_funder(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:funding": [{"@type": ["schema:MonetaryGrant"], "schema:funder": _org("Some Funder")}]}
        )
        enricher.enrich(doc, country="AR")
        resolver.resolve.assert_called_once_with("Some Funder", "AR")

    def test_no_country_defaults_to_none(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": _org("Some Publisher")})
        enricher.enrich(doc)
        resolver.resolve.assert_called_once_with("Some Publisher", None)


# --------------------------------------------------------------------------


class TestProvenance:
    """IdentifierEnricher: every attached identifier carries match provenance."""

    def test_creator_identifiers_carry_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:creator": [_org("Ministerio de Hacienda")]})
        enricher.enrich(doc)
        entry = doc.get_field("schema:creator")[0]["schema:identifier"][0]
        assert entry["matched_via"] == "ror_affiliation"
        assert entry["confidence"] == 0.95
        assert entry["status"] == "auto"

    def test_funder_identifiers_carry_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:funding": [{"@type": ["schema:MonetaryGrant"], "schema:funder": _org("Some Funder")}]}
        )
        enricher.enrich(doc)
        entry = doc.get_field("schema:funding")[0]["schema:funder"]["schema:identifier"][0]
        assert entry["matched_via"] == "ror_affiliation"
        assert entry["confidence"] == 0.95
        assert entry["status"] == "auto"

    def test_affiliation_identifier_carries_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _org(
                        "Some Org",
                        identifiers=[{"schema:propertyID": "ROR", "schema:value": "already-set"}],
                        affiliations=[_org("Universidad de Chile")],
                    )
                ]
            }
        )
        enricher.enrich(doc)
        affil = doc.get_field("schema:creator")[0]["schema:affiliation"][0]
        entry = affil["schema:identifier"][0]
        assert entry["matched_via"] == "ror_affiliation"
        assert entry["confidence"] == 0.95
        assert entry["status"] == "auto"

    def test_publisher_identifier_carries_provenance(self) -> None:
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": _org("Some Publisher")})
        enricher.enrich(doc)
        entry = doc.get_field("schema:publisher")["schema:identifier"][0]
        assert entry["matched_via"] == "ror_affiliation"
        assert entry["confidence"] == 0.95
        assert entry["status"] == "auto"

    def test_orcid_identifier_carries_provenance(self) -> None:
        resolver = MagicMock()
        resolver.resolve_person.return_value = IdentifierMatch(
            orcid_id="0000-0002-1825-0097",
            org_name="Jane Roe",
            confidence=1.0,
            matched_via="orcid_search",
            status="auto",
        )
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:creator": [_person("Roe, Jane", "Jane", "Roe")]})
        enricher.enrich(doc)
        entry = doc.get_field("schema:creator")[0]["schema:identifier"][0]
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
        doc = _doc_with_fields({"schema:publisher": _org("Some Publisher")})
        enricher.enrich(doc)
        entry = doc.get_field("schema:publisher")["schema:identifier"][0]
        assert entry["matched_via"] == "override"

    def test_review_status_org_match_is_not_auto_attached(self) -> None:
        """Deliberate behavior change (2026-08-25, code review follow-up):
        org identifiers (ROR/ISNI) get the same status=="auto" gate ORCID
        already had -- a wrong PID is worse than a missing one, so an
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
        doc = _doc_with_fields({"schema:creator": [_org("Some Org")]})
        enricher.enrich(doc)
        assert doc.get_field("schema:creator")[0]["schema:identifier"] == []


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
        doc = _doc_with_fields(
            {
                "schema:creator": [
                    _org(
                        "Some Org",
                        identifiers=[{"schema:propertyID": "ROR", "schema:value": "already-set"}],
                        affiliations=[_org("Universidad de Chile")],
                    )
                ]
            }
        )
        enricher.enrich(doc)
        affil = doc.get_field("schema:creator")[0]["schema:affiliation"][0]
        assert affil["schema:identifier"] == []

    def test_publisher_identifier_not_attached_when_review(self) -> None:
        resolver = _review_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": _org("Some Publisher")})
        enricher.enrich(doc)
        assert doc.get_field("schema:publisher")["schema:identifier"] == []

    def test_funder_identifiers_not_attached_when_review(self) -> None:
        resolver = _review_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields(
            {"schema:funding": [{"@type": ["schema:MonetaryGrant"], "schema:funder": _org("Some Funder")}]}
        )
        enricher.enrich(doc)
        assert doc.get_field("schema:funding")[0]["schema:funder"]["schema:identifier"] == []

    def test_auto_status_still_attaches_normally(self) -> None:
        """Control: the existing 'auto' fixture (_mock_resolver) still works
        unchanged -- this gate only rejects 'review'/'nomatch', not 'auto'."""
        resolver = _mock_resolver()
        enricher = IdentifierEnricher(resolver)
        doc = _doc_with_fields({"schema:publisher": _org("Some Publisher")})
        enricher.enrich(doc)
        assert (
            doc.get_field("schema:publisher")["schema:identifier"][0]["schema:value"]
            == "https://ror.org/01h6h5x94"
        )
