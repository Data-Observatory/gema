"""Client for the ROR (Research Organization Registry) API v2.

Provides ``RORClient`` for searching organizations via the ``?affiliation=``
and ``?query=`` endpoints, plus static helpers for extracting ISNI, parent
organization, and display name from ROR v2 records.

Docs: https://ror.readme.io/docs/rest-api
Base URL: https://api.ror.org/v2/organizations
"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

_RESERVED_CHARS = "\\" + "+-&|!(){}[]^\"~*?:/"


class RORClient:
    """Client for the ROR (Research Organization Registry) API v2.

    Docs: https://ror.readme.io/docs/rest-api
    Base URL: https://api.ror.org/v2/organizations
    """

    BASE_URL = "https://api.ror.org/v2/organizations"

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        client_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize. If http_client is None, creates a new httpx.Client.

        Args:
            http_client: Optional pre-configured httpx.Client. If None, a new
                client is created with the given timeout and redirect-following.
            client_id: Optional ROR API Client-Id header value (see
                https://ror.org/api-client-id). Sent on every request when set.
            timeout: Request timeout in seconds. Only used when http_client
                is None.
        """
        self._client = http_client or httpx.Client(
            timeout=timeout, follow_redirects=True
        )
        self._client_id = client_id

    def search_affiliation(self, affiliation_text: str) -> dict[str, Any] | None:
        """Search using the ``?affiliation=`` endpoint.

        Returns the organization dict (full ROR record) if an item with
        ``chosen=True`` is found, otherwise None.

        The affiliation endpoint accepts messy affiliation strings
        (departments, addresses, punctuation). ROR ranks results and marks
        the best match with ``chosen=True``. ROR explicitly says: do NOT use
        the ``score`` field to select matches — only use ``chosen=True``.

        Args:
            affiliation_text: Messy affiliation string (e.g. "Dept of Biology,
                              Harvard University, Cambridge, MA").

        Returns:
            ROR organization record dict, or None if no chosen match.
        """
        params = {"affiliation": affiliation_text}
        data = self._request(params)
        items = data.get("items", [])
        for item in items:
            if item.get("chosen") is True:
                org = item.get("organization")
                if org is not None:
                    return cast("dict[str, Any]", org)
        return None

    def search_query(self, name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search using the ``?query=`` endpoint.

        Returns a list of organization dicts (up to limit). These are
        full ROR records directly — no chosen/score wrapper.

        The query endpoint searches names and external_ids. Results are
        ranked by relevance but there is no chosen flag.

        Args:
            name: Organization name to search for.
            limit: Maximum results to return (default 5). Sliced
                client-side — ROR v2's ``?query=`` endpoint rejects a
                ``limit`` request parameter outright
                (``"query parameter 'limit' is illegal"``), confirmed
                against the live API.

        Returns:
            List of ROR organization record dicts.
        """
        escaped = escape_query(name)
        params = {"query": escaped}
        data = self._request(params)
        items = data.get("items", [])
        return list(items[:limit])

    def close(self) -> None:
        """Close the HTTP client if we own it."""
        self._client.close()

    def __enter__(self) -> RORClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        """Execute GET request to ROR API with headers.

        Args:
            params: Query parameter dict.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses.
        """
        headers = {"User-Agent": "gema/0.1 (identifier-resolver)"}
        if self._client_id:
            headers["Client-Id"] = self._client_id
        response = self._client.get(self.BASE_URL, params=params, headers=headers)
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())


# ------------------------------------------------------------------
# Static helpers — operate on ROR v2 organization record dicts
# ------------------------------------------------------------------


def get_display_name(org: dict[str, Any]) -> str:
    """Extract the canonical display name from a ROR v2 record.

    In v2, names are stored in the ``names`` array. The display name has
    ``ror_display`` in its ``types`` list. Falls back to first name value.

    Args:
        org: A ROR v2 organization record dict.

    Returns:
        The display name string, or empty string if no names are present.
    """
    names = org.get("names", [])
    for name in names:
        if "ror_display" in name.get("types", []):
            value = name.get("value")
            if isinstance(value, str):
                return value
    if names:
        first_value = names[0].get("value")
        if isinstance(first_value, str):
            return first_value
    return ""


def extract_isni(org: dict[str, Any]) -> str | None:
    """Extract ISNI from a ROR v2 record's external_ids.

    In v2, external_ids is a list of
    ``{"type": "isni", "preferred": str|None, "all": [str]}``.
    ISNI values are formatted with spaces (e.g. "0000 0001 0726 5157").
    Normalize by removing ALL spaces.

    Args:
        org: A ROR v2 organization record dict.

    Returns:
        The normalized ISNI (16 chars, no spaces) or None if not found.
    """
    external_ids = org.get("external_ids", [])
    for entry in external_ids:
        if entry.get("type") != "isni":
            continue
        preferred = entry.get("preferred")
        if isinstance(preferred, str) and preferred:
            return preferred.replace(" ", "")
        all_values = entry.get("all") or []
        if all_values and isinstance(all_values[0], str):
            return all_values[0].replace(" ", "")
        return None
    return None


def extract_country(org: dict[str, Any]) -> str | None:
    """Extract the ISO 3166-1 alpha-2 country code from a ROR v2 record.

    In v2, ``locations`` is a list of
    ``{"geonames_details": {"country_code": str, ...}, ...}``. A ROR record
    normally carries exactly one location — this reads the first.

    Args:
        org: A ROR v2 organization record dict.

    Returns:
        The two-letter country code (uppercased), or None if not present.
    """
    locations = org.get("locations", [])
    if not locations or not isinstance(locations[0], dict):
        return None
    geonames = locations[0].get("geonames_details")
    if not isinstance(geonames, dict):
        return None
    code = geonames.get("country_code")
    return code.upper() if isinstance(code, str) and code else None


def extract_parent(org: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract parent organization from a ROR v2 record's relationships.

    In v2, relationships is a list of
    ``{"id": str, "label": str, "type": str}``. Looks for ``type == "parent"``.

    Args:
        org: A ROR v2 organization record dict.

    Returns:
        Tuple of ``(parent_ror_url, parent_name)`` or ``(None, None)`` if no
        parent relationship is present.
    """
    relationships = org.get("relationships", [])
    for rel in relationships:
        if rel.get("type") != "parent":
            continue
        parent_id = rel.get("id")
        parent_label = rel.get("label")
        parent_id_str = parent_id if isinstance(parent_id, str) else None
        parent_label_str = parent_label if isinstance(parent_label, str) else None
        return parent_id_str, parent_label_str
    return None, None


def escape_query(term: str) -> str:
    """Escape Elasticsearch reserved characters for the ``?query=`` endpoint.

    Reserved chars: ``+ - = && || > < ! ( ) { } [ ] ^ " ~ * ? : \\ /``
    Each is prefixed with a backslash.

    Args:
        term: Raw query string.

    Returns:
        Escaped query string safe for the ROR ``?query=`` parameter.
    """
    escaped: list[str] = []
    for char in term:
        if char in _RESERVED_CHARS:
            escaped.append("\\" + char)
        else:
            escaped.append(char)
    return "".join(escaped)
