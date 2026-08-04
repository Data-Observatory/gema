"""Client for the ORCID Public API v3.0.

Unlike ROR and ISNI, ORCID's public API requires a bearer token even for
public read-only search. The token comes from a free, self-service OAuth
``client_credentials`` registration (https://orcid.org/developer-tools) —
there is no fully anonymous endpoint. Without ``ORCID_CLIENT_ID`` /
``ORCID_CLIENT_SECRET`` configured, this client disables itself and returns
no results rather than raising, matching every other client in this package.

Docs: https://info.orcid.org/documentation/api-tutorials/api-tutorial-searching-the-orcid-registry/
Base URL: https://pub.orcid.org/v3.0/
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://orcid.org/oauth/token"
BASE_URL = "https://pub.orcid.org/v3.0"


class ORCIDClient:
    """Client for the ORCID Public API v3.0 person search endpoint.

    Requires ``ORCID_CLIENT_ID`` / ``ORCID_CLIENT_SECRET`` (or explicit
    constructor args) to obtain a ``client_credentials`` bearer token.
    ``client_credentials`` tokens are long-lived (years), so the token is
    fetched once and cached in-memory for the client's lifetime.
    """

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = http_client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._client_id = client_id or os.environ.get("ORCID_CLIENT_ID")
        self._client_secret = client_secret or os.environ.get("ORCID_CLIENT_SECRET")
        self._token: str | None = None
        self._token_fetch_failed = False

    @property
    def enabled(self) -> bool:
        """Whether credentials are configured at all (does not guarantee a valid token)."""
        return bool(self._client_id and self._client_secret)

    def search_person(
        self,
        given_names: str,
        family_name: str,
        affiliation_org_name: str | None = None,
        max_records: int = 5,
    ) -> dict[str, Any]:
        """Search ORCID for a person by exact given/family name (+ optional affiliation).

        Returns ``{"num_found": int, "orcids": list[str]}`` — ``orcids`` are
        bare 16-char ORCID iDs (e.g. "0000-0002-1825-0097"), most-relevant
        first, capped at *max_records*. Returns ``{"num_found": 0, "orcids": []}``
        if credentials are missing, the token request fails, or the search
        itself fails — never raises.
        """
        if not self.enabled:
            logger.debug("ORCID client has no credentials configured — skipping search")
            return {"num_found": 0, "orcids": []}

        token = self._get_token()
        if token is None:
            return {"num_found": 0, "orcids": []}

        query = f'family-name:"{family_name}" AND given-names:"{given_names}"'
        if affiliation_org_name:
            query += f' AND affiliation-org-name:"{affiliation_org_name}"'

        try:
            response = self._client.get(
                f"{BASE_URL}/search/",
                params={"q": query, "rows": str(max_records)},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("ORCID search failed for %r %r: %s", given_names, family_name, exc)
            return {"num_found": 0, "orcids": []}

        results = data.get("result") or []
        orcids = []
        for item in results:
            path = (item.get("orcid-identifier") or {}).get("path")
            if isinstance(path, str) and path:
                orcids.append(path)

        return {"num_found": int(data.get("num-found", len(orcids))), "orcids": orcids}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ORCIDClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str | None:
        if self._token is not None:
            return self._token
        if self._token_fetch_failed:
            return None
        try:
            response = self._client.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                    "scope": "/read-public",
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            token = cast("dict[str, Any]", response.json()).get("access_token")
        except httpx.HTTPError as exc:
            logger.warning("ORCID OAuth token request failed: %s", exc)
            self._token_fetch_failed = True
            return None
        if not isinstance(token, str) or not token:
            logger.warning("ORCID OAuth token response missing access_token")
            self._token_fetch_failed = True
            return None
        self._token = token
        return token
