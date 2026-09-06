"""Post-merge identifier enricher — resolves org/person names to ROR/ISNI/ORCID.

Retargeted from DataCite field names to CDIF field names as part of the
CDIF/Croissant pivot (docs/codata_mcp_croissant_cdifspecs.md sec 3.5).
Walks ``schema:creator``, ``schema:publisher``, and ``schema:funding`` on
a CDIF-generated MetadataDocument. ``schema:creator`` is a JSON-LD
order-preserving list -- ``{"@list": [<entry>, ...]}``, per the vendored
schema's own field description -- not a bare array like ``schema:publisher``
or ``schema:funding``; use ``types.jsonld_list_unwrap`` to read it, never
index into it directly. ``CDIFDiscoveryProfile.merge_agent_results`` is what
wraps it at generation time -- agents themselves still emit a plain list,
the natural Instructor/structured-output shape.

Internal shape convention this module (and agents.yaml's prompts) commit
to for these three fields -- CURIE-keyed at every nesting level (verified
against the vendored schema.json's ``$defs`` -- see
docs/cdif_pivot_implementation_plan.md's changelog entry for the pass that
fixed this) so real JSON-LD tooling (rdflib/pyld) can actually resolve
these properties via ``@context`` instead of silently dropping a bare key:

    creator/contributor/publisher/funder entry (Person or Organization)::

        {
            "@type": ["schema:Person"] | ["schema:Organization"],
            "schema:name": str,
            "schema:givenName": str,   # Person only -- gema extension: a
                                        # real schema.org term the vendored
                                        # profile just doesn't reference;
                                        # used for citation formatting and
                                        # ORCID matching, not part of this
                                        # profile's Person def itself.
            "schema:familyName": str,  # Person only -- same extension.
            "schema:identifier": {"schema:propertyID": str, "schema:value": str, "schema:url": str},
            "schema:sameAs": [ {"@id": str}, ... ],  # overflow, see below (Open Question #22)
            "schema:affiliation": [ <Organization entry, same shape> ],
        }

    ``schema:identifier`` may also carry ``matched_via``, ``confidence``,
    ``status`` as bare (non-CURIE) sibling keys -- gema-internal audit
    trail from this enricher, deliberately outside the JSON-LD graph,
    never meant to round-trip through real JSON-LD tooling. Left
    un-prefixed on purpose; don't "fix" them. ``schema:sameAs`` overflow
    entries carry none of this (Open Question #22): the vendored schema
    only allows a bare string/``{"@id": ...}`` reference there, and the
    provenance is identical to the sibling ``schema:identifier`` entry's
    anyway (same ``IdentifierMatch``), so nothing is lost by omitting it.

    schema:funding entry (MonetaryGrant)::

        {
            "@type": ["schema:MonetaryGrant"],
            "schema:name": str,              # award title
            "schema:identifier": {"schema:propertyID": str, "schema:value": str},  # award number/URI
            "schema:funder": <Organization entry>,
            "schema:description": str,       # funding stream
        }

    Cardinality (Open Question #16, resolved): the vendored schema models
    ``Person``/``Organization``/``MonetaryGrant``'s ``schema:identifier`` as
    *singular* (one Identifier object or a string), not a list -- but a
    resolved organization/person can legitimately carry more than one
    identifier at once (e.g. both a ROR and an ISNI). Resolution: write the
    first/preferred match (``_SCHEME_ORDER``: ROR before ISNI for orgs) as
    the singular ``schema:identifier``, and any additional matches into
    ``schema:sameAs`` -- the vendored ``Person``/``Organization`` ``$defs``
    ship exactly that sibling array for this purpose ("other identifiers
    for the organization/person"). See ``types.entity_identifiers`` (the
    shared reader every exporter now goes through) and this module's own
    ``_write_identifiers`` (the shared writer). When there's no identifier
    at all, the key is omitted entirely -- never an empty dict/list -- same
    "absent, not empty" convention as constraint C6's ``schema:sameAs``.
"""

from __future__ import annotations

import logging
from typing import Any

from metadata_enricher.enrichers.identifier_resolver import IdentifierResolver
from metadata_enricher.enrichers.identifier_types import IdentifierMatch
from metadata_enricher.types import MetadataDocument, first_type_label, jsonld_list_unwrap

logger = logging.getLogger(__name__)

# ISNI's canonical resolver path is "/isni/<id>", not bare "/<id>" -- matches
# pid_validator.resolve_pid and isni_client's own isni_uri construction.
# Getting this wrong only mattered cosmetically pre-#22 (schema:value carried
# the real id regardless); post-#22 this URL is the *only* surviving record
# for an overflow ISNI written into schema:sameAs, so it must be right.
_SCHEME_URI = {
    "ROR": "https://ror.org",
    "ISNI": "https://isni.org/isni",
    "ORCID": "https://orcid.org",
}

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


def _scheme_url(scheme: str, id_value: str) -> str:
    """Resolvable URL for *id_value* under *scheme*. ROR's own API returns
    ``id`` as an already-full URI (``https://ror.org/027nn6b17``, not a
    bare ``027nn6b17``) -- unconditionally prefixing it produced doubled
    URLs (``https://ror.org/https://ror.org/...``) in real recorded
    output. ISNI/ORCID values are bare, so this is a no-op for them."""
    if id_value.startswith(("http://", "https://")):
        return id_value
    return f"{_SCHEME_URI[scheme]}/{id_value}"


def _identifier_entries(match: IdentifierMatch) -> list[dict[str, Any]]:
    """``schema:identifier``-shaped PropertyValue list, one entry per scheme
    the match found, carrying provenance (why this identifier was attached)
    as sibling keys — a curated catalog needs that more than OpenAlex's bare
    numeric confidence does, since a wrong PID here is worse than a missing
    one.
    """
    return [
        {
            "schema:propertyID": scheme,
            "schema:value": id_value,
            "schema:url": id_value if scheme == "ORCID" else _scheme_url(scheme, id_value),
            "matched_via": match.matched_via,
            "confidence": match.confidence,
            "status": match.status,
        }
        for id_value, scheme in _all_identifiers(match)
    ]


def _is_auto(match: IdentifierMatch, kind: str, name: str) -> bool:
    """True if *match* is unambiguous enough to auto-attach.

    A wrong PID is worse than a missing one, so an ambiguous match
    (``status != "auto"``) is logged, not attached. ``status`` is one field
    on the whole match, not per-scheme — a ROR+ISNI merge where either side
    was ambiguous rejects both identifiers together, same all-or-nothing
    shape as ORCID.
    """
    if match.status != "auto":
        logger.info(
            "%s match for %r is ambiguous (status=%s) — not auto-attaching",
            kind, name, match.status,
        )
        return False
    return True


def _has_real_identifier(entry: dict[str, Any]) -> bool:
    """True if *entry* already carries a real (non-empty) identifier.

    Handles both shapes: the pre-enrichment placeholder the LLM writes
    (an empty list, per config/agents.yaml's prompts) and the post-#16
    singular-dict shape this module writes (see ``_write_identifiers``) --
    plus a bare list with real entries, defensively, for anything
    hand-built or not yet migrated to the singular shape.
    """
    identifiers = entry.get("schema:identifier")
    if isinstance(identifiers, dict):
        return bool(identifiers.get("schema:value"))
    if isinstance(identifiers, list):
        return any(isinstance(i, dict) and i.get("schema:value") for i in identifiers)
    return False


def _strip_empty_identifier(entry: dict[str, Any]) -> None:
    """Removes an empty ``schema:identifier`` placeholder (``[]`` -- what
    config/agents.yaml's prompts instruct the LLM to emit when nothing was
    found) so an unresolved entity ends up with the key *absent*, matching
    the vendored schema's singular Identifier-or-string type (Open Question
    #16) -- not present as a still-list-shaped `[]`, which would be exactly
    the pre-#16 cardinality violation this module exists to fix. A no-op
    when the key already holds a real (non-empty) identifier -- only ever
    deletes a falsy value ([]/{}), never something `_write_identifiers`/an
    enrichment call just wrote."""
    if "schema:identifier" in entry and not entry["schema:identifier"]:
        del entry["schema:identifier"]


def _write_identifiers(entry: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    """Writes *entries* (preferred match first) as the singular
    ``schema:identifier`` slot the vendored Person/Organization/
    MonetaryGrant defs actually want, plus ``schema:sameAs`` overflow for
    anything beyond the first (Open Question #16 -- see module docstring).
    No-op if *entries* is empty; never writes an empty dict/list.

    Open Question #22, resolved: the vendored ``$defs``' ``schema:sameAs``
    is ``anyOf: [string, {"@id": string}]`` on these nested entities, not
    the full PropertyValue shape ``schema:identifier`` itself uses -- an
    overflow entry here is written as a bare ``{"@id": <resolvable URL>}``
    reference. Provenance (``matched_via``/``confidence``/``status``) is
    dropped for overflow entries: every field in *entries* comes from the
    same single ``IdentifierMatch`` (see ``_identifier_entries``), so the
    identical triple already lives on the sibling ``schema:identifier``
    slot -- nothing is lost. ``types.entity_identifiers`` reverse-parses
    the scheme back out of the URL host for callers that want it."""
    if not entries:
        return
    entry["schema:identifier"] = entries[0]
    if len(entries) > 1:
        entry["schema:sameAs"] = [
            {"@id": overflow["schema:url"] if overflow.get("schema:url") else overflow.get("schema:value", "")}
            for overflow in entries[1:]
        ]


class IdentifierEnricher:
    """Enriches a MetadataDocument with resolved ROR/ISNI/ORCID identifiers.

    Walks ``schema:creator``, ``schema:publisher``, and ``schema:funding``
    after the LLM merge step. For each organization name without an
    identifier, calls ``IdentifierResolver.resolve`` to look up ROR/ISNI via
    API. For personal creators with a given/family name split, calls
    ``IdentifierResolver.resolve_person`` to look up ORCID.

    An identifier is only written when the match is unambiguous
    (``status == "auto"``) — a wrong PID is worse than a missing one, so an
    ambiguous match (``status == "review"``) is logged (see ``_is_auto``)
    but never attached.

    Fields already populated by the LLM are preserved — the enricher only
    fills EMPTY identifier fields.
    """

    def __init__(self, resolver: IdentifierResolver) -> None:
        self._resolver = resolver

    def enrich(self, document: MetadataDocument, country: str | None = None) -> MetadataDocument:
        """Enrich *document* in place. *country* (ISO 3166-1 alpha-2, e.g.
        from ``country_extractor.CountryExtractor``) is an optional hint
        passed through to org resolution — see ``IdentifierResolver.resolve``.
        """
        self._enrich_creators(document, country)
        self._enrich_publisher(document, country)
        self._enrich_funding(document, country)
        return document

    def _enrich_creators(self, document: MetadataDocument, country: str | None = None) -> None:
        # schema:creator is a {"@list": [...]} JSON-LD construct, not a bare
        # array (see jsonld_list_unwrap's docstring) -- unwrap to get the
        # actual list. Entries are mutated in place, so no write-back is
        # needed: the unwrapped list is the same object the document holds.
        creators = jsonld_list_unwrap(document.get_field("schema:creator"))
        if not creators:
            return
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            is_person = first_type_label(creator.get("@type")) == "Person"

            if is_person:
                if not _has_real_identifier(creator):
                    self._enrich_personal_creator(creator)
            else:
                name = creator.get("schema:name", "")
                if name and not _has_real_identifier(creator):
                    match = self._resolver.resolve(name, country)
                    if match is not None and _is_auto(match, "org", name):
                        _write_identifiers(creator, _identifier_entries(match))
            _strip_empty_identifier(creator)

            self._enrich_affiliations(creator, country)

    def _enrich_affiliations(self, entry: dict[str, Any], country: str | None) -> None:
        affiliations = entry.get("schema:affiliation", [])
        if not isinstance(affiliations, list):
            return
        for affil in affiliations:
            if not isinstance(affil, dict):
                continue
            if _has_real_identifier(affil):
                continue
            affil_name = affil.get("schema:name", "")
            if affil_name:
                affil_match = self._resolver.resolve(affil_name, country)
                if affil_match is not None and _is_auto(affil_match, "affiliation", affil_name):
                    _write_identifiers(affil, _identifier_entries(affil_match))
            _strip_empty_identifier(affil)

    def _enrich_personal_creator(self, creator: dict[str, Any]) -> None:
        given_name = creator.get("schema:givenName", "")
        family_name = creator.get("schema:familyName", "")
        if not given_name or not family_name:
            return
        affiliations = creator.get("schema:affiliation", [])
        affiliation_name = None
        if isinstance(affiliations, list) and affiliations:
            first = affiliations[0]
            if isinstance(first, dict):
                affiliation_name = first.get("schema:name") or None

        match = self._resolver.resolve_person(given_name, family_name, affiliation_name)
        if match is not None and match.orcid_id and _is_auto(match, "ORCID", f"{given_name} {family_name}"):
            creator["schema:identifier"] = {
                "schema:propertyID": "ORCID",
                "schema:value": match.orcid_id,
                "schema:url": f"https://orcid.org/{match.orcid_id}",
                "matched_via": match.matched_via,
                "confidence": match.confidence,
                "status": match.status,
            }
        _strip_empty_identifier(creator)

    def _enrich_publisher(self, document: MetadataDocument, country: str | None = None) -> None:
        publisher = document.get_field("schema:publisher")
        if not isinstance(publisher, dict) or _has_real_identifier(publisher):
            return
        name = publisher.get("schema:name", "")
        if name:
            pub_match = self._resolver.resolve(name, country)
            if pub_match is not None and _is_auto(pub_match, "publisher", name):
                _write_identifiers(publisher, _identifier_entries(pub_match))
        _strip_empty_identifier(publisher)

    def _enrich_funding(self, document: MetadataDocument, country: str | None = None) -> None:
        funding = document.get_field("schema:funding")
        if not funding or not isinstance(funding, list):
            return
        for grant in funding:
            if not isinstance(grant, dict):
                continue
            funder = grant.get("schema:funder")
            if not isinstance(funder, dict):
                continue
            if _has_real_identifier(funder):
                continue
            name = funder.get("schema:name", "")
            if name:
                funder_match = self._resolver.resolve(name, country)
                if funder_match is not None and _is_auto(funder_match, "funder", name):
                    _write_identifiers(funder, _identifier_entries(funder_match))
            _strip_empty_identifier(funder)
