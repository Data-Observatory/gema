"""Data models for identifier resolution results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IdentifierMatch(BaseModel):
    """Represents a resolved organization identifier from ROR/ISNI APIs.

    Attributes:
        ror_id: ROR identifier URL (e.g. "https://ror.org/01qe7f394") or None.
        isni_id: ISNI identifier as 16-digit string (e.g. "000000040628717X") or None.
                 Normalized — no spaces, no URI prefix.
        org_name: Canonical organization name from the API response.
        confidence: Match confidence score from 0.0 to 1.0.
        matched_via: How the match was found. One of:
                     "ror_affiliation", "ror_query_fuzzy", "isni_sru".
        parent_ror_id: Parent organization ROR URL (from ROR relationships) or None.
        parent_name: Parent organization display name or None.
        status: Match quality indicator. One of:
                "auto" (unambiguous match, safe to use),
                "review" (ambiguous, small gap between candidates),
                "nomatch" (no match found — but org_name will still be set).
    """

    model_config = ConfigDict(extra="forbid")

    ror_id: str | None = None
    isni_id: str | None = None
    org_name: str = ""
    confidence: float = 0.0
    matched_via: str = ""
    parent_ror_id: str | None = None
    parent_name: str | None = None
    status: str = "nomatch"
