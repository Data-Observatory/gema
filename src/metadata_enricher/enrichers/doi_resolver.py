"""Post-merge DOI-resolver enricher — backfills weak/missing fields for
DOI-identified resources from Crossref's authoritative record, instead of
relying purely on LLM extraction from title/description text.
"""

from __future__ import annotations

import logging
from typing import Any

from metadata_enricher.enrichers.crossref_client import CrossrefClient
from metadata_enricher.types import MetadataDocument

logger = logging.getLogger(__name__)


def _date_parts_to_str(date_parts: object) -> str:
    """Crossref's ``{"date-parts": [[YYYY, MM, DD]]}"`` -> "YYYY[-MM[-DD]]".

    Only as many components as Crossref actually provided — never pads a
    month/day that wasn't in the source data.
    """
    if not isinstance(date_parts, list) or not date_parts:
        return ""
    parts = date_parts[0]
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], int):
        return ""
    if len(parts) == 1:
        return f"{parts[0]:04d}"
    if len(parts) == 2 and isinstance(parts[1], int):
        return f"{parts[0]:04d}-{parts[1]:02d}"
    if len(parts) >= 3 and isinstance(parts[1], int) and isinstance(parts[2], int):
        return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    return ""


class DOIResolverEnricher:
    """Backfills EMPTY fields on DOI-identified resources from Crossref.

    Only acts when ``resource.identifier_type == "DOI"``. Titles/creators/
    publishers/resource.publication_year are only ever filled when
    completely empty — a field the LLM agents already populated (even
    partially) is left untouched, same "preserve LLM values" policy as
    ``IdentifierEnricher``. ``dates`` is the one exception: an agent-produced
    date of a different type (e.g. ``Collected``) does not block adding the
    authoritative Crossref ``Issued`` date alongside it -- only an existing
    ``Issued``-typed entry blocks it. Scope is deliberately narrow: titles,
    creators (authors, personal or organizational), publishers, an Issued
    date, and publication_year — the fields Crossref's public Works API
    reliably returns. Abstracts are skipped (rare, and often JATS-XML-tagged
    when present — not worth the parsing complexity for a field most DOI
    records don't carry anyway).
    """

    def __init__(self, client: CrossrefClient) -> None:
        self._client = client

    def enrich(self, document: MetadataDocument) -> MetadataDocument:
        resource = document.get_field("resource")
        if not isinstance(resource, dict) or resource.get("identifier_type") != "DOI":
            return document
        doi = resource.get("identifier", "")
        if not doi:
            return document

        try:
            work = self._client.get_work(doi)
        except Exception as exc:
            logger.warning("Crossref lookup failed for DOI %r: %s", doi, exc)
            return document
        if work is None:
            return document

        self._backfill_titles(document, work)
        self._backfill_creators(document, work)
        self._backfill_publisher(document, work)
        self._backfill_issued_date(document, work)
        return document

    def _backfill_titles(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        if document.get_field("titles"):
            return
        titles = work.get("title")
        if not isinstance(titles, list) or not titles or not titles[0]:
            return
        document.set_field(
            "titles", [{"name": titles[0], "title_type": "MainTitle", "language": ""}]
        )

    def _backfill_creators(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        """Personal authors (family+given) and organizational authors
        (Crossref emits these as a bare {"name": ...}, no family/given) both
        become creators -- institutional DOI authorship is common for the
        government/agency resources this project targets, and was previously
        dropped entirely by skipping any author without a `family`."""
        if document.get_field("creators"):
            return
        authors = work.get("author")
        if not isinstance(authors, list) or not authors:
            return
        creators: list[dict[str, Any]] = []
        for author in authors:
            if not isinstance(author, dict):
                continue
            affiliations = [
                {
                    "affiliation": affil["name"],
                    "affiliation_identifier": "",
                    "affiliation_identifier_scheme": "",
                }
                for affil in author.get("affiliation") or []
                if isinstance(affil, dict) and affil.get("name")
            ]
            family = author.get("family", "")
            if family:
                # "Apellido, Nombre" -- matches creators_publishers' own
                # convention (config/agents.yaml), not Crossref's raw
                # given/family order, so DOI-backfilled and LLM-produced
                # creator_name values are directly comparable.
                given = author.get("given", "")
                name = f"{family}, {given}" if given else family
                creators.append(
                    {
                        "creator_name": name,
                        "creator_name_type": "Personal",
                        "given_name": given,
                        "family_name": family,
                        "email": "",
                        "genre": "",
                        "type": "Person",
                        "contributor_type": "",
                        "name_identifiers": [],
                        "affiliations": affiliations,
                    }
                )
            else:
                org_name = author.get("name", "")
                if not org_name:
                    continue
                creators.append(
                    {
                        "creator_name": org_name,
                        "creator_name_type": "Organizational",
                        "given_name": "",
                        "family_name": "",
                        "email": "",
                        "genre": "",
                        "type": "Organization",
                        "contributor_type": "",
                        "name_identifiers": [],
                        "affiliations": affiliations,
                    }
                )
        if creators:
            document.set_field("creators", creators)

    def _backfill_publisher(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        if document.get_field("publishers"):
            return
        publisher = work.get("publisher")
        if not publisher:
            return
        document.set_field(
            "publishers",
            [
                {
                    "publisher_name": publisher,
                    "publisher_identifier": "",
                    "publisher_identifier_scheme": "",
                    "publisher_scheme_uri": "",
                    "lang": "",
                }
            ],
        )

    def _backfill_issued_date(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        """Only skips if an Issued-typed date already exists -- an agent-
        produced date of a different type (e.g. Collected) must not block
        backfilling the authoritative Crossref Issued date alongside it.
        Also backfills resource.publication_year, previously never touched
        by this enricher despite the year being available right here."""
        issued = work.get("issued")
        if not isinstance(issued, dict):
            return
        date_str = _date_parts_to_str(issued.get("date-parts"))
        if not date_str:
            return

        dates = document.get_field("dates")
        existing_dates = dates if isinstance(dates, list) else []
        has_issued = any(
            isinstance(d, dict) and d.get("date_type") == "Issued" for d in existing_dates
        )
        if not has_issued:
            document.set_field(
                "dates",
                [
                    *existing_dates,
                    {
                        "date": date_str,
                        "date_type": "Issued",
                        "date_information": (
                            "Fecha de publicación obtenida del registro Crossref para este DOI"
                        ),
                    },
                ],
            )

        resource = document.get_field("resource")
        if isinstance(resource, dict) and not resource.get("publication_year"):
            document.set_field("resource", {**resource, "publication_year": date_str[:4]})
