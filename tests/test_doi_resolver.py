"""Tests for enrichers.doi_resolver (CDIF field names)."""

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


def _doi_doc(**extra: object) -> MetadataDocument:
    fields = {"schema:identifier": [{"schema:propertyID": "DOI", "schema:value": "10.1/x"}]}
    fields.update(extra)
    return _doc_with_fields(fields)


class TestNotADOI:
    def test_skips_url_identified_resources(self) -> None:
        client = _mock_client()
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"schema:identifier": [{"schema:propertyID": "URL", "schema:value": "https://x.org"}]})
        enricher.enrich(doc)
        client.get_work.assert_not_called()

    def test_skips_when_identifier_field_missing(self) -> None:
        client = _mock_client()
        enricher = DOIResolverEnricher(client)
        doc = MetadataDocument()
        enricher.enrich(doc)
        client.get_work.assert_not_called()

    def test_skips_when_identifier_value_empty(self) -> None:
        client = _mock_client()
        enricher = DOIResolverEnricher(client)
        doc = _doc_with_fields({"schema:identifier": [{"schema:propertyID": "DOI", "schema:value": ""}]})
        enricher.enrich(doc)
        client.get_work.assert_not_called()


class TestCrossrefLookupFailure:
    def test_no_work_found_leaves_document_unchanged(self) -> None:
        client = _mock_client(work=None)
        enricher = DOIResolverEnricher(client)
        doc = _doi_doc()
        result = enricher.enrich(doc)
        assert result.get_field("schema:name") is None

    def test_client_exception_is_caught_not_propagated(self) -> None:
        client = MagicMock()
        client.get_work.side_effect = RuntimeError("network down")
        enricher = DOIResolverEnricher(client)
        doc = _doi_doc()
        result = enricher.enrich(doc)
        assert result is doc
        assert result.get_field("schema:name") is None


class TestBackfillName:
    def test_fills_empty_name(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:name") == "Global Seismic Event Catalog 2021"

    def test_preserves_existing_name(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc(**{"schema:name": "LLM title"})
        enricher.enrich(doc)
        assert doc.get_field("schema:name") == "LLM title"


class TestBackfillCreators:
    def test_fills_empty_creators_from_authors(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc()
        enricher.enrich(doc)
        # Backfilled schema:creator is wrapped {"@list": [...]} (constraint
        # C4), same as what merge_agent_results would have produced.
        # "Apellido, Nombre" -- matches creators_publishers' own convention
        # (config/agents.yaml), not Crossref's raw given/family order.
        # Second author has no given name -- name falls back to family only.
        assert doc.get_field("schema:creator") == {
            "@list": [
                {
                    "@type": ["schema:Person"],
                    "schema:name": "Doe, Jane",
                    "schema:givenName": "Jane",
                    "schema:familyName": "Doe",
                    "schema:identifier": [],
                    "schema:affiliation": [
                        {
                            "@type": ["schema:Organization"],
                            "schema:name": "GFZ Potsdam",
                            "schema:identifier": [],
                        }
                    ],
                },
                {
                    "@type": ["schema:Person"],
                    "schema:name": "Smith",
                    "schema:givenName": "",
                    "schema:familyName": "Smith",
                    "schema:identifier": [],
                    "schema:affiliation": [],
                },
            ]
        }

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
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:creator") == {
            "@list": [
                {
                    "@type": ["schema:Organization"],
                    "schema:name": "Deutsches GeoForschungsZentrum GFZ",
                    "schema:identifier": [],
                    "schema:affiliation": [],
                }
            ]
        }

    def test_preserves_existing_creators(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc(**{"schema:creator": [{"schema:name": "LLM Author"}]})
        enricher.enrich(doc)
        assert doc.get_field("schema:creator") == [{"schema:name": "LLM Author"}]

    def test_author_without_family_or_org_name_is_skipped(self) -> None:
        client = _mock_client(work={**MOCK_WORK, "author": [{"given": "Jane", "family": ""}]})
        enricher = DOIResolverEnricher(client)
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:creator") is None


class TestBackfillPublisher:
    def test_fills_empty_publisher(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:publisher") == {
            "@type": ["schema:Organization"],
            "schema:name": "GFZ Potsdam",
            "schema:identifier": [],
        }

    def test_preserves_existing_publisher(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc(**{"schema:publisher": {"schema:name": "LLM Publisher"}})
        enricher.enrich(doc)
        assert doc.get_field("schema:publisher") == {"schema:name": "LLM Publisher"}


class TestBackfillDatePublished:
    def test_fills_empty_date_published_full_precision(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:datePublished") == "2021-03-15"

    def test_year_only_precision(self) -> None:
        client = _mock_client(work={**MOCK_WORK, "issued": {"date-parts": [[2021]]}})
        enricher = DOIResolverEnricher(client)
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:datePublished") == "2021"

    def test_year_month_precision(self) -> None:
        client = _mock_client(work={**MOCK_WORK, "issued": {"date-parts": [[2021, 3]]}})
        enricher = DOIResolverEnricher(client)
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:datePublished") == "2021-03"

    def test_preserves_existing_date_published(self) -> None:
        enricher = DOIResolverEnricher(_mock_client())
        doc = _doi_doc(**{"schema:datePublished": "1999"})
        enricher.enrich(doc)
        assert doc.get_field("schema:datePublished") == "1999"

    def test_missing_issued_leaves_date_published_empty(self) -> None:
        client = _mock_client(work={k: v for k, v in MOCK_WORK.items() if k != "issued"})
        enricher = DOIResolverEnricher(client)
        doc = _doi_doc()
        enricher.enrich(doc)
        assert doc.get_field("schema:datePublished") is None
