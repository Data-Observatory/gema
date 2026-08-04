"""PID validation — format + live-resolution checks for DOI/ROR/ISNI.

Shared by the pipeline (automatic, on every run — see ``Pipeline._process_resource``)
and ``scripts/validate_real_output.py`` (detailed batch reporting on top of the
same checks). One place owns "is this PID real" so the two never drift apart.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
ROR_RE = re.compile(r"^https://ror\.org/0[a-hjkmnp-tv-z0-9]{6}[0-9]{2}$")
ISNI_RE = re.compile(r"^\d{15}[\dX]$")
ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

_KNOWN_SCHEMES = ("DOI", "ROR", "ISNI", "ORCID")


@dataclass
class PidCheck:
    scheme: str
    value: str
    location: str
    format_ok: bool
    resolved: bool | None  # None = not checked (--no-resolve, or the check itself errored)

    @property
    def problem(self) -> str | None:
        """A one-line description if this PID failed a check, else None."""
        if not self.format_ok:
            return f"malformed {self.scheme} at {self.location}: {self.value!r}"
        if self.resolved is False:
            return f"{self.scheme} does not resolve: {self.value!r} ({self.location})"
        return None


def _strip_doi_prefix(value: str) -> str:
    return re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", value.strip(), flags=re.IGNORECASE)


def _strip_orcid_prefix(value: str) -> str:
    return re.sub(r"^https?://orcid\.org/", "", value.strip(), flags=re.IGNORECASE)


def _mod_11_2_checksum_ok(digits: str) -> bool:
    """ISO 7064 MOD 11-2 check digit — used by both ISNI and ORCID (last char may be 'X' = 10)."""
    total = 0
    for ch in digits[:15]:
        total = (total + int(ch)) * 2
    remainder = total % 11
    check = (12 - remainder) % 11
    expected = "X" if check == 10 else str(check)
    return digits[15] == expected


def validate_pid_format(scheme: str, value: str) -> tuple[bool, str]:
    """Format/checksum check. Returns (ok, normalized_value)."""
    scheme_norm = scheme.strip().upper()
    if scheme_norm == "DOI":
        stripped = _strip_doi_prefix(value)
        return bool(DOI_RE.match(stripped)), stripped
    if scheme_norm == "ROR":
        return bool(ROR_RE.match(value.strip())), value.strip()
    if scheme_norm == "ISNI":
        digits = value.strip().replace(" ", "")
        if not ISNI_RE.match(digits):
            return False, digits
        return _mod_11_2_checksum_ok(digits), digits
    if scheme_norm == "ORCID":
        stripped = _strip_orcid_prefix(value)
        if not ORCID_RE.match(stripped):
            return False, stripped
        return _mod_11_2_checksum_ok(stripped.replace("-", "")), stripped
    return True, value  # unknown scheme — nothing to check


def _resolved_from_status(status_code: int) -> bool | None:
    """Map an HTTP status to True/False/None (inconclusive).

    Only 404 means "confirmed not found." Everything else that isn't a
    success (403, 429, 5xx — bot-protection, rate limits, outages) is
    inconclusive, not a failure: observed live against isni.org, which
    403s automated lookups of ISNIs that are otherwise perfectly valid.
    Treating that as "does not resolve" would be a false positive.
    """
    if status_code < 400:
        return True
    if status_code == 404:
        return False
    return None


def resolve_pid(client: httpx.Client, scheme: str, value: str) -> bool | None:
    """Hit the real registry for *value*. Returns True/False, or None if inconclusive."""
    scheme_norm = scheme.strip().upper()
    try:
        if scheme_norm == "DOI":
            doi = _strip_doi_prefix(value)
            resp = client.get(f"https://doi.org/{doi}", follow_redirects=True, timeout=15.0)
            return _resolved_from_status(resp.status_code)
        if scheme_norm == "ROR":
            ror_id = value.strip().rstrip("/").rsplit("/", 1)[-1]
            resp = client.get(f"https://api.ror.org/v2/organizations/{ror_id}", timeout=15.0)
            return _resolved_from_status(resp.status_code)
        if scheme_norm == "ISNI":
            isni = value.strip().replace(" ", "")
            resp = client.get(f"https://isni.org/isni/{isni}", follow_redirects=True, timeout=15.0)
            return _resolved_from_status(resp.status_code)
        if scheme_norm == "ORCID":
            orcid = _strip_orcid_prefix(value)
            resp = client.get(
                f"https://orcid.org/{orcid}",
                headers={"Accept": "application/orcid+json"},
                follow_redirects=True,
                timeout=15.0,
            )
            return _resolved_from_status(resp.status_code)
    except httpx.HTTPError as exc:
        logger.debug("PID resolution request failed for %s %s: %s", scheme, value, exc)
        return None
    return None


def _walk_scheme_pairs(
    obj: Any, id_key: str, scheme_key: str, location: str
) -> list[tuple[str, str, str]]:
    """Find (scheme, value, location) triples anywhere a dict has both id_key and scheme_key."""
    found: list[tuple[str, str, str]] = []
    if isinstance(obj, dict):
        value = obj.get(id_key)
        scheme = obj.get(scheme_key)
        if isinstance(value, str) and value and isinstance(scheme, str) and scheme:
            found.append((scheme, value, location))
        for k, v in obj.items():
            found.extend(_walk_scheme_pairs(v, id_key, scheme_key, f"{location}.{k}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(_walk_scheme_pairs(item, id_key, scheme_key, f"{location}[{i}]"))
    return found


def extract_pids(output: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return (scheme, value, location) triples for every identifier found in *output*.

    Covers the field-name variants used across the DataCite schema:
    name_identifier(_scheme), affiliation_identifier(_scheme),
    publisher_identifier(_scheme), funder_identifier(_type), plus DOIs
    surfaced via resource.identifier / related_identifiers / alternate_identifiers.
    """
    triples: list[tuple[str, str, str]] = []
    triples += _walk_scheme_pairs(output, "name_identifier", "name_identifier_scheme", "root")
    triples += _walk_scheme_pairs(
        output, "affiliation_identifier", "affiliation_identifier_scheme", "root"
    )
    triples += _walk_scheme_pairs(
        output, "publisher_identifier", "publisher_identifier_scheme", "root"
    )
    triples += _walk_scheme_pairs(output, "funder_identifier", "funder_identifier_type", "root")

    resource = output.get("resource")
    if isinstance(resource, dict):
        ident = resource.get("identifier")
        ident_type = resource.get("identifier_type", "")
        if isinstance(ident, str) and ident and "doi" in str(ident_type).lower():
            triples.append(("DOI", ident, "resource.identifier"))

    for group, id_key, type_key in (
        ("related_identifiers", "related_identifier", "related_identifier_type"),
        ("alternate_identifiers", "alternate_identifier", "alternate_identifier_type"),
    ):
        for i, item in enumerate(output.get(group, []) or []):
            if not isinstance(item, dict):
                continue
            if "doi" in str(item.get(type_key, "")).lower():
                value = item.get(id_key)
                if isinstance(value, str) and value:
                    triples.append(("DOI", value, f"{group}[{i}].{id_key}"))

    return triples


def validate_pids(
    output: dict[str, Any], *, resolve: bool = True, client: httpx.Client | None = None
) -> list[PidCheck]:
    """Extract every PID from *output* and check its format (and, live registry).

    ORCID resolution uses orcid.org's public content-negotiation endpoint
    (``Accept: application/orcid+json`` on ``https://orcid.org/{id}``) —
    no OAuth token needed, unlike the search API used to *find* an ORCID
    iD by name (see ``ORCIDClient.search_person``). Confirmed live: a
    real ORCID iD returns 200 with no credentials.

    If *resolve* is True and *client* is None, a throwaway client is created
    and closed internally. Never raises — a failed resolution check becomes
    ``resolved=None`` (unchecked), not an exception.
    """
    owns_client = False
    if resolve and client is None:
        client = httpx.Client(headers={"User-Agent": "metagen-pid-validator/0.1"})
        owns_client = True

    try:
        checks: list[PidCheck] = []
        for scheme, raw_value, location in extract_pids(output):
            scheme_norm = scheme.strip().upper()
            if scheme_norm not in _KNOWN_SCHEMES:
                continue
            format_ok, normalized = validate_pid_format(scheme_norm, raw_value)
            resolved: bool | None = None
            if format_ok and resolve and client is not None:
                resolved = resolve_pid(client, scheme_norm, normalized)
            checks.append(
                PidCheck(
                    scheme=scheme_norm,
                    value=raw_value,
                    location=location,
                    format_ok=format_ok,
                    resolved=resolved,
                )
            )
        return checks
    finally:
        if owns_client and client is not None:
            client.close()
