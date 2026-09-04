"""Post-merge DOI-resolver enricher — backfills weak/missing fields for
DOI-identified resources from Crossref's authoritative record, instead of
relying purely on LLM extraction from title/description text.

Retargeted to CDIF field names as part of the CDIF/Croissant pivot
(docs/codata_mcp_croissant_cdifspecs.md sec 3.5) — see
enrichers/identifier_enricher.py's module docstring for the shared
creator/organization entry shape convention this module also produces.
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


def _doi_identifier(doc: MetadataDocument) -> str:
    """The DOI value, if schema:identifier carries one -- else empty."""
    for entry in doc.get_field("schema:identifier", []) or []:
        if isinstance(entry, dict) and str(entry.get("propertyID", "")).upper() == "DOI":
            return str(entry.get("value", ""))
    return ""


class DOIResolverEnricher:
    """Backfills EMPTY fields on DOI-identified resources from Crossref.

    Only acts when ``schema:identifier`` carries a DOI-typed entry.
    ``schema:name``/``schema:creator``/``schema:publisher``/
    ``schema:datePublished`` are only ever filled when completely empty — a
    field the LLM agents already populated (even partially) is left
    untouched, same "preserve LLM values" policy as ``IdentifierEnricher``.
    Scope is deliberately narrow: name, creators (authors, personal or
    organizational), publisher, and the published date — the fields
    Crossref's public Works API reliably returns. Abstracts are skipped
    (rare, and often JATS-XML-tagged when present — not worth the parsing
    complexity for a field most DOI records don't carry anyway).
    """

    def __init__(self, client: CrossrefClient) -> None:
        self._client = client

    def enrich(self, document: MetadataDocument) -> MetadataDocument:
        doi = _doi_identifier(document)
        if not doi:
            return document

        try:
            work = self._client.get_work(doi)
        except Exception as exc:
            logger.warning("Crossref lookup failed for DOI %r: %s", doi, exc)
            return document
        if work is None:
            return document

        self._backfill_name(document, work)
        self._backfill_creators(document, work)
        self._backfill_publisher(document, work)
        self._backfill_date_published(document, work)
        return document

    def _backfill_name(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        if document.get_field("schema:name"):
            return
        titles = work.get("title")
        if not isinstance(titles, list) or not titles or not titles[0]:
            return
        document.set_field("schema:name", str(titles[0]))

    def _backfill_creators(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        """Personal authors (family+given) and organizational authors
        (Crossref emits these as a bare {"name": ...}, no family/given) both
        become creators -- institutional DOI authorship is common for the
        government/agency resources this project targets."""
        if document.get_field("schema:creator"):
            return
        authors = work.get("author")
        if not isinstance(authors, list) or not authors:
            return
        creators: list[dict[str, Any]] = []
        for author in authors:
            if not isinstance(author, dict):
                continue
            affiliations = [
                {"@type": "schema:Organization", "name": affil["name"], "schema:identifier": []}
                for affil in author.get("affiliation") or []
                if isinstance(affil, dict) and affil.get("name")
            ]
            family = author.get("family", "")
            if family:
                given = author.get("given", "")
                name = f"{family}, {given}" if given else family
                creators.append(
                    {
                        "@type": "schema:Person",
                        "name": name,
                        "given_name": given,
                        "family_name": family,
                        "schema:identifier": [],
                        "schema:affiliation": affiliations,
                    }
                )
            else:
                org_name = author.get("name", "")
                if not org_name:
                    continue
                creators.append(
                    {
                        "@type": "schema:Organization",
                        "name": org_name,
                        "schema:identifier": [],
                        "schema:affiliation": affiliations,
                    }
                )
        if creators:
            document.set_field("schema:creator", creators)

    def _backfill_publisher(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        if document.get_field("schema:publisher"):
            return
        publisher = work.get("publisher")
        if not publisher:
            return
        document.set_field(
            "schema:publisher",
            {"@type": "schema:Organization", "name": publisher, "schema:identifier": []},
        )

    def _backfill_date_published(self, document: MetadataDocument, work: dict[str, Any]) -> None:
        """Backfills schema:datePublished only if entirely empty -- an
        agent-produced date of a different kind (e.g. dateCreated) does not
        block adding the authoritative Crossref issued date here, since
        they are different CDIF properties, not competing values of one
        field."""
        issued = work.get("issued")
        if not isinstance(issued, dict):
            return
        date_str = _date_parts_to_str(issued.get("date-parts"))
        if not date_str:
            return

        if not document.get_field("schema:datePublished"):
            document.set_field("schema:datePublished", date_str)
