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

    Only acts when ``resource.identifier_type == "DOI"``. Only ever fills a
    field that is completely empty — a field the LLM agents already
    populated (even partially) is left untouched, same "preserve LLM
    values" policy as ``IdentifierEnricher``. Scope is deliberately narrow:
    titles, creators (authors), publishers, and an Issued date — the fields
    Crossref's public Works API reliably returns. Abstracts are skipped
    (rare, and often JATS-XML-tagged when present — not worth the parsing
    complexity for a field most DOI records don't carry anyway).
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
        if document.get_field("creators"):
            return
        authors = work.get("author")
        if not isinstance(authors, list) or not authors:
            return
        creators: list[dict[str, Any]] = []
        for author in authors:
            if not isinstance(author, dict):
                continue
            family = author.get("family", "")
            if not family:
                continue
            given = author.get("given", "")
            name = f"{given} {family}".strip() if given else family
            affiliations = [
                {
                    "affiliation": affil["name"],
                    "affiliation_identifier": "",
                    "affiliation_identifier_scheme": "",
                }
                for affil in author.get("affiliation") or []
                if isinstance(affil, dict) and affil.get("name")
            ]
            creators.append(
                {
                    "creator_name": name,
                    "creator_name_type": "Personal",
                    "given_name": given,
                    "family_name": family,
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
                }
            ],
        )

    def _backfill_issued_date(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        if document.get_field("dates"):
            return
        issued = work.get("issued")
        if not isinstance(issued, dict):
            return
        date_str = _date_parts_to_str(issued.get("date-parts"))
        if not date_str:
            return
        document.set_field(
            "dates",
            [
                {
                    "date": date_str,
                    "date_type": "Issued",
                    "date_information": (
                        "Fecha de publicación obtenida del registro Crossref para este DOI"
                    ),
                }
            ],
        )
