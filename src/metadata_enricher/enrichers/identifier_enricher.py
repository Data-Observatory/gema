"""Post-merge identifier enricher — resolves org/person names to ROR/ISNI/ORCID."""

from __future__ import annotations

import logging
from typing import Any

from metadata_enricher.enrichers.identifier_resolver import IdentifierResolver
from metadata_enricher.enrichers.identifier_types import IdentifierMatch
from metadata_enricher.types import MetadataDocument

logger = logging.getLogger(__name__)

_SCHEME_URI = {"ROR": "https://ror.org", "ISNI": "https://isni.org", "ORCID": "https://orcid.org"}

# Fixed, stable output order — ROR first (most actionable for orgs), then ISNI,
# then ORCID (person matches only; never co-occurs with ROR/ISNI on the same match).
_SCHEME_ORDER = ("ROR", "ISNI", "ORCID")


def _all_identifiers(match: IdentifierMatch | None) -> list[tuple[str, str]]:
    """Every identifier *match* actually found, as (id_value, scheme) pairs.

    A resolved org can carry both a ROR and an ISNI at once (``resolve``
    merges independent hits from both registries) — this returns all of
    them, not just one "preferred" scheme.
    """
    if match is None:
        return []
    by_scheme = {"ROR": match.ror_id, "ISNI": match.isni_id, "ORCID": match.orcid_id}
    return [(value, scheme) for scheme in _SCHEME_ORDER if (value := by_scheme[scheme])]


def _preferred_identifier(match: IdentifierMatch | None) -> tuple[str, str] | None:
    """Single identifier for schema fields that only hold one (affiliation/publisher).

    DataCite's affiliationIdentifier and publisherIdentifier are 0..1 fields —
    unlike nameIdentifiers/funderIdentifiers, they cannot hold a second entry.
    ROR is preferred there since it's the more actionable identifier for an
    organization; ISNI is used only when ROR wasn't found.
    """
    identifiers = _all_identifiers(match)
    return identifiers[0] if identifiers else None


def _identifier_entry(
    id_value: str, scheme: str, id_key: str, scheme_key: str, match: IdentifierMatch
) -> dict[str, Any]:
    """One name_identifier/funder_identifier-shaped list entry, carrying
    the match's provenance (why this identifier was attached) as sibling
    keys — a curated catalog needs that more than OpenAlex's bare numeric
    confidence does, since a wrong PID here is worse than a missing one.
    """
    return {
        id_key: id_value,
        scheme_key: scheme,
        "scheme_uri": _SCHEME_URI[scheme],
        "matched_via": match.matched_via,
        "confidence": match.confidence,
        "status": match.status,
    }


def _provenance(field_prefix: str, match: IdentifierMatch) -> dict[str, Any]:
    """Provenance keys for a single-slot field (affiliation_identifier,
    publisher_identifier) — prefixed so they never collide with another
    key on the same dict, unlike a name_identifiers/funder_identifiers list
    entry, which is already its own namespace (see _identifier_entry).
    """
    return {
        f"{field_prefix}_matched_via": match.matched_via,
        f"{field_prefix}_confidence": match.confidence,
        f"{field_prefix}_status": match.status,
    }


class IdentifierEnricher:
    """Enriches a MetadataDocument with resolved ROR/ISNI/ORCID identifiers.

    Walks creators, publishers, and funding_references after the LLM merge
    step. For each organization name without an identifier, calls
    ``IdentifierResolver.resolve`` to look up ROR/ISNI via API. For personal
    creators with a given/family name split, calls
    ``IdentifierResolver.resolve_person`` to look up ORCID.

    Every identifier a resolver call actually found is written where the
    schema allows more than one (``name_identifiers``, ``funder_identifiers``).
    Where the schema only allows one (``affiliation_identifier``,
    ``publisher_identifier``), ROR is preferred over ISNI.

    ORCID matches are only written when unambiguous (``status == "auto"``,
    i.e. exactly one search hit) — a wrong ORCID on a person is worse than a
    missing one, so ambiguous matches (``status == "review"``) are logged but
    not attached.

    Fields already populated by the LLM are preserved — the enricher only
    fills EMPTY identifier fields.

    Every identifier attached also carries its match provenance —
    ``matched_via``/``confidence``/``status`` as sibling keys on a
    ``name_identifiers``/``funder_identifiers`` list entry, or
    ``{field}_matched_via``/``{field}_confidence``/``{field}_status`` for a
    single-slot field (``affiliation_identifier``, ``publisher_identifier``)
    — so a human reviewing the catalog can tell an unambiguous ROR
    affiliation hit from an ambiguous fuzzy match without re-running
    resolution.
    """

    def __init__(self, resolver: IdentifierResolver) -> None:
        self._resolver = resolver

    def enrich(self, document: MetadataDocument, country: str | None = None) -> MetadataDocument:
        """Enrich *document* in place. *country* (ISO 3166-1 alpha-2, e.g.
        from ``country_extractor.CountryExtractor``) is an optional hint
        passed through to org resolution — see ``IdentifierResolver.resolve``.
        """
        self._enrich_creators(document, country)
        self._enrich_publishers(document, country)
        self._enrich_funding_references(document, country)
        return document

    def _enrich_creators(self, document: MetadataDocument, country: str | None = None) -> None:
        creators = document.get_field("creators")
        if not creators or not isinstance(creators, list):
            return
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            name_type = creator.get("creator_name_type", "")
            name_identifiers = creator.get("name_identifiers", [])
            has_real_id = isinstance(name_identifiers, list) and any(
                isinstance(ni, dict) and ni.get("name_identifier") for ni in name_identifiers
            )

            if name_type == "Personal":
                if not has_real_id:
                    self._enrich_personal_creator(creator)
                continue

            name = creator.get("creator_name", "")
            if name and not has_real_id:
                match = self._resolver.resolve(name, country)
                if match is not None:
                    identifiers = _all_identifiers(match)
                    if identifiers:
                        creator["name_identifiers"] = [
                            _identifier_entry(
                                id_value, scheme, "name_identifier", "name_identifier_scheme", match
                            )
                            for id_value, scheme in identifiers
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
                    affil_match = self._resolver.resolve(affil_name, country)
                    if affil_match is None:
                        continue
                    identifier = _preferred_identifier(affil_match)
                    if identifier:
                        id_value, scheme = identifier
                        affil["affiliation_identifier"] = id_value
                        affil["affiliation_identifier_scheme"] = scheme
                        affil.update(_provenance("affiliation_identifier", affil_match))

    def _enrich_personal_creator(self, creator: dict[str, Any]) -> None:
        given_name = creator.get("given_name", "")
        family_name = creator.get("family_name", "")
        if not given_name or not family_name:
            return
        affiliations = creator.get("affiliations", [])
        affiliation_name = None
        if isinstance(affiliations, list) and affiliations:
            first = affiliations[0]
            if isinstance(first, dict):
                affiliation_name = first.get("affiliation") or None

        match = self._resolver.resolve_person(given_name, family_name, affiliation_name)
        if match is None or not match.orcid_id:
            return
        if match.status != "auto":
            logger.info(
                "ORCID match for %s %s is ambiguous (status=%s) — not auto-attaching",
                given_name, family_name, match.status,
            )
            return
        creator["name_identifiers"] = [
            _identifier_entry(
                f"https://orcid.org/{match.orcid_id}",
                "ORCID",
                "name_identifier",
                "name_identifier_scheme",
                match,
            )
        ]

    def _enrich_publishers(self, document: MetadataDocument, country: str | None = None) -> None:
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
            pub_match = self._resolver.resolve(name, country)
            if pub_match is None:
                continue
            identifier = _preferred_identifier(pub_match)
            if identifier:
                id_value, scheme = identifier
                publisher["publisher_identifier"] = id_value
                publisher["publisher_identifier_scheme"] = scheme
                publisher["publisher_scheme_uri"] = _SCHEME_URI[scheme]
                publisher.update(_provenance("publisher_identifier", pub_match))

    def _enrich_funding_references(
        self, document: MetadataDocument, country: str | None = None
    ) -> None:
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
            funder_match = self._resolver.resolve(name, country)
            if funder_match is None:
                continue
            identifiers = _all_identifiers(funder_match)
            if identifiers:
                ref["funder_identifiers"] = [
                    _identifier_entry(
                        id_value,
                        scheme,
                        "funder_identifier",
                        "funder_identifier_type",
                        funder_match,
                    )
                    for id_value, scheme in identifiers
                ]
