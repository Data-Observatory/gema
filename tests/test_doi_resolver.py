"""Tests for enrichers.doi_resolver."""

from __future__ import annotations

from unittest.mock import MagicMock

from metadata_enricher.enrichers.doi_resolver import DOIResolverEnricher
from metadata_enricher.types import MetadataDocument

MOCK_WORK = {
    "title": ["Global Seismic Event Catalog 2021"],
    "publisher": "GFZ Potsdam",
    "author": [
        {"given": "Jane", "family": "Doe", "affiliation": [{"name": "GFZ Potsdam"}]},
        {"given": "", "family": "Smith", "affiliation": []},
    ],
    "issued": {"date-parts": [[2021, 3, 15]]},
}


def _doc_with_fields(fields: dict) -> MetadataDocument:
    doc = MetadataDocument()
    for k, v in fields.items():
        doc.set_field(k, v)
    return doc


def _mock_client(work: dict | None = MOCK_WORK) -> MagicMock:
    client = MagicMock()
    client.get_work.return_value = work
    return client


class TestNotADOI:
    def test_skips_url_identified_resources(self) -> None:
        client = _mock_client()
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "https://x.org", "identifier_type": "URL"}})
        enricher.enrich(doc)
        client.get_work.assert_not_called()

    def test_skips_when_resource_field_missing(self) -> None:
        client = _mock_client()
        enricher = DOIResolverEnricher(client)
        doc = MetadataDocument()
        enricher.enrich(doc)
        client.get_work.assert_not_called()

    def test_skips_when_identifier_empty(self) -> None:
        client = _mock_client()
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        client.get_work.assert_not_called()


class TestCrossrefLookupFailure:
    def test_no_work_found_leaves_document_unchanged(self) -> None:
        client = _mock_client(work=None)
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        result = enricher.enrich(doc)
        assert result.get_field("titles") is None

    def test_client_exception_is_caught_not_propagated(self) -> None:
        client = MagicMock()
        client.get_work.side_effect = RuntimeError("network down")
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        result = enricher.enrich(doc)
        assert result is doc
        assert result.get_field("titles") is None


class TestBackfillTitles:
    def test_fills_empty_titles(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        assert doc.get_field("titles") == [
            {"name": "Global Seismic Event Catalog 2021", "title_type": "MainTitle", "language": ""}
        ]

    def test_preserves_existing_titles(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields(
            {
                "resource": {"identifier": "10.1/x", "identifier_type": "DOI"},
                "titles": [{"name": "LLM title", "title_type": "MainTitle", "language": "en"}],
            }
        )
        enricher.enrich(doc)
        assert doc.get_field("titles") == [
            {"name": "LLM title", "title_type": "MainTitle", "language": "en"}
        ]


class TestBackfillCreators:
    def test_fills_empty_creators_from_authors(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        creators = doc.get_field("creators")
        # "Apellido, Nombre" -- matches creators_publishers' own convention
        # (config/agents.yaml), not Crossref's raw given/family order, and
        # the full normalizer key set (email/genre/type/contributor_type),
        # not a bespoke subset -- so DOI-backfilled and LLM-produced
        # creators are structurally identical.
        assert creators[0] == {
            "creator_name": "Doe, Jane",
            "creator_name_type": "Personal",
            "given_name": "Jane",
            "family_name": "Doe",
            "email": "",
            "genre": "",
            "type": "Person",
            "contributor_type": "",
            "name_identifiers": [],
            "affiliations": [
                {
                    "affiliation": "GFZ Potsdam",
                    "affiliation_identifier": "",
                    "affiliation_identifier_scheme": "",
                }
            ],
        }
        # Second author has no given name -- creator_name falls back to family only.
        assert creators[1]["creator_name"] == "Smith"
        assert creators[1]["affiliations"] == []

    def test_organizational_author_becomes_organizational_creator(self) -> None:
        """Crossref emits institutional authors as a bare {"name": ...},
        no family/given -- these must not be silently dropped, since
        institutional DOI authorship is common for the government/agency
        resources this project targets."""
        client = _mock_client(
            work={
                **MOCK_WORK,
                "author": [{"name": "Deutsches GeoForschungsZentrum GFZ", "affiliation": []}],
            }
        )
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        creators = doc.get_field("creators")
        assert creators == [
            {
                "creator_name": "Deutsches GeoForschungsZentrum GFZ",
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
        ]

    def test_preserves_existing_creators(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields(
            {
                "resource": {"identifier": "10.1/x", "identifier_type": "DOI"},
                "creators": [{"creator_name": "LLM Author"}],
            }
        )
        enricher.enrich(doc)
        assert doc.get_field("creators") == [{"creator_name": "LLM Author"}]

    def test_author_without_family_or_org_name_is_skipped(self) -> None:
        client = _mock_client(work={**MOCK_WORK, "author": [{"given": "Jane", "family": ""}]})
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        assert doc.get_field("creators") is None


class TestBackfillPublisher:
    def test_fills_empty_publisher(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        assert doc.get_field("publishers") == [
            {
                "publisher_name": "GFZ Potsdam",
                "publisher_identifier": "",
                "publisher_identifier_scheme": "",
                "publisher_scheme_uri": "",
                "lang": "",
            }
        ]

    def test_preserves_existing_publisher(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields(
            {
                "resource": {"identifier": "10.1/x", "identifier_type": "DOI"},
                "publishers": [{"publisher_name": "LLM Publisher"}],
            }
        )
        enricher.enrich(doc)
        assert doc.get_field("publishers") == [{"publisher_name": "LLM Publisher"}]


class TestBackfillIssuedDate:
    def test_fills_empty_dates_full_precision(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        dates = doc.get_field("dates")
        assert dates[0]["date"] == "2021-03-15"
        assert dates[0]["date_type"] == "Issued"
        assert dates[0]["date_information"]

    def test_year_only_precision(self) -> None:
        client = _mock_client(work={**MOCK_WORK, "issued": {"date-parts": [[2021]]}})
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        assert doc.get_field("dates")[0]["date"] == "2021"

    def test_year_month_precision(self) -> None:
        client = _mock_client(work={**MOCK_WORK, "issued": {"date-parts": [[2021, 3]]}})
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        assert doc.get_field("dates")[0]["date"] == "2021-03"

    def test_appends_issued_alongside_other_dated_type(self) -> None:
        """A non-Issued date (e.g. agent-produced Collected) must not block
        adding the authoritative Crossref Issued date alongside it -- only
        an existing Issued-typed entry should."""
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields(
            {
                "resource": {"identifier": "10.1/x", "identifier_type": "DOI"},
                "dates": [{"date": "2020", "date_type": "Collected", "date_information": ""}],
            }
        )
        enricher.enrich(doc)
        dates = doc.get_field("dates")
        assert {"date": "2020", "date_type": "Collected", "date_information": ""} in dates
        issued = [d for d in dates if d["date_type"] == "Issued"]
        assert issued and issued[0]["date"] == "2021-03-15"

    def test_preserves_existing_issued_date(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields(
            {
                "resource": {"identifier": "10.1/x", "identifier_type": "DOI"},
                "dates": [{"date": "2020", "date_type": "Issued", "date_information": ""}],
            }
        )
        enricher.enrich(doc)
        assert doc.get_field("dates") == [
            {"date": "2020", "date_type": "Issued", "date_information": ""}
        ]

    def test_missing_issued_leaves_dates_empty(self) -> None:
        client = _mock_client(work={k: v for k, v in MOCK_WORK.items() if k != "issued"})
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"resource": {"identifier": "10.1/x", "identifier_type": "DOI"}})
        enricher.enrich(doc)
        assert doc.get_field("dates") is None


class TestBackfillPublicationYear:
    def test_fills_empty_publication_year(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields(
            {"resource": {"identifier": "10.1/x", "identifier_type": "DOI", "publication_year": ""}}
        )
        enricher.enrich(doc)
        assert doc.get_field("resource")["publication_year"] == "2021"

    def test_preserves_existing_publication_year(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doc_with_fields(
            {
                "resource": {
                    "identifier": "10.1/x",
                    "identifier_type": "DOI",
                    "publication_year": "1999",
                }
            }
        )
        enricher.enrich(doc)
        assert doc.get_field("resource")["publication_year"] == "1999"
