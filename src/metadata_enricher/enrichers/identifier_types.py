"""Data models for identifier resolution results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IdentifierMatch(BaseModel):
    """Represents a resolved organization identifier from ROR/ISNI APIs.

    Attributes:
        ror_id: ROR identifier URL (e.g. "https://ror.org/01qe7f394") or None.
        isni_id: ISNI identifier as 16-digit string (e.g. "000000040628717X") or None.
                 Normalized — no spaces, no URI prefix.
        orcid_id: ORCID iD (e.g. "0000-0002-1825-0097") for a *person* match, or None.
                  Only ever set by ``IdentifierResolver.resolve_person`` — organization
                  matches (``resolve``) never populate this field.
        org_name: Canonical organization name from the API response. For person
                  matches (``orcid_id`` set), this holds the person's display name.
        confidence: Match confidence score from 0.0 to 1.0.
        matched_via: How the match was found. One of:
                     "ror_affiliation", "ror_query_fuzzy", "isni_sru", "orcid_search",
                     or a "+"-joined combination when both ROR and ISNI independently
                     confirmed a match (e.g. "ror_affiliation+isni_sru").
        parent_ror_id: Parent organization ROR URL (from ROR relationships) or None.
        parent_name: Parent organization display name or None.
        status: Match quality indicator. One of:
                "auto" (unambiguous match, safe to use),
                "review" (ambiguous, small gap between candidates, or — for
                ORCID — more than one search hit),
                "nomatch" (no match found — but org_name will still be set).
    """

    model_config = ConfigDict(extra="forbid")

    ror_id: str | None = None
    isni_id: str | None = None
    orcid_id: str | None = None
    org_name: str = ""
    confidence: float = 0.0
    matched_via: str = ""
    parent_ror_id: str | None = None
    parent_name: str | None = None
    status: str = "nomatch"
