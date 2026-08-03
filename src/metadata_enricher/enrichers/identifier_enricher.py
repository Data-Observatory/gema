"""Post-merge identifier enricher — resolves org names to ROR/ISNI."""

from __future__ import annotations

import logging

from metadata_enricher.enrichers.identifier_resolver import IdentifierResolver
from metadata_enricher.types import MetadataDocument

logger = logging.getLogger(__name__)


class IdentifierEnricher:
    """Enriches a MetadataDocument with resolved ROR/ISNI identifiers.

    Walks creators, publishers, and funding_references after the LLM merge
    step. For each organization name without an identifier, calls
    IdentifierResolver to look up the ROR/ISNI via API.

    Personal creators (creator_name_type == "Personal") are skipped —
    individuals don't have ROR IDs.

    Fields already populated by the LLM are preserved — the enricher only
    fills EMPTY identifier fields.
    """

    def __init__(self, resolver: IdentifierResolver) -> None:
        self._resolver = resolver

    def enrich(self, document: MetadataDocument) -> MetadataDocument:
        self._enrich_creators(document)
        self._enrich_publishers(document)
        self._enrich_funding_references(document)
        return document

    def _enrich_creators(self, document: MetadataDocument) -> None:
        creators = document.get_field("creators")
        if not creators or not isinstance(creators, list):
            return
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            name_type = creator.get("creator_name_type", "")
            if name_type == "Personal":
                continue
            name = creator.get("creator_name", "")
            if not name:
                continue
            name_identifiers = creator.get("name_identifiers", [])
            has_real_id = isinstance(name_identifiers, list) and any(
                isinstance(ni, dict) and ni.get("name_identifier") for ni in name_identifiers
            )
            if not has_real_id:
                match = self._resolver.resolve(name)
                if match and match.ror_id:
                    creator["name_identifiers"] = [
                        {
                            "name_identifier": match.ror_id,
                            "name_identifier_scheme": "ROR",
                            "scheme_uri": "https://ror.org",
                        }
                    ]
            affiliations = creator.get("affiliations", [])
            if isinstance(affiliations, list):
                for affil in affiliations:
                    if not isinstance(affil, dict):
                        continue
                    existing_id = affil.get("affiliation_identifier", "")
                    if existing_id:
                        continue
                    affil_name = affil.get("affiliation", "")
                    if not affil_name:
                        continue
                    match = self._resolver.resolve(affil_name)
                    if match and match.ror_id:
                        affil["affiliation_identifier"] = match.ror_id
                        affil["affiliation_identifier_scheme"] = "ROR"

    def _enrich_publishers(self, document: MetadataDocument) -> None:
        publishers = document.get_field("publishers")
        if not publishers or not isinstance(publishers, list):
            return
        for publisher in publishers:
            if not isinstance(publisher, dict):
                continue
            existing_id = publisher.get("publisher_identifier", "")
            if existing_id:
                continue
            name = publisher.get("publisher_name", "")
            if not name:
                continue
            match = self._resolver.resolve(name)
            if match and match.ror_id:
                publisher["publisher_identifier"] = match.ror_id
                publisher["publisher_identifier_scheme"] = "ROR"
                publisher["publisher_scheme_uri"] = "https://ror.org"

    def _enrich_funding_references(self, document: MetadataDocument) -> None:
        funding = document.get_field("funding_references")
        if not funding or not isinstance(funding, list):
            return
        for ref in funding:
            if not isinstance(ref, dict):
                continue
            funder_ids = ref.get("funder_identifiers", [])
            has_real_id = isinstance(funder_ids, list) and any(
                isinstance(fi, dict) and fi.get("funder_identifier") for fi in funder_ids
            )
            if has_real_id:
                continue
            name = ref.get("funder_name", "")
            if not name:
                continue
            match = self._resolver.resolve(name)
            if match and match.ror_id:
                ref["funder_identifiers"] = [
                    {
                        "funder_identifier": match.ror_id,
                        "funder_identifier_type": "ROR",
                        "scheme_uri": "https://ror.org",
                    }
                ]
