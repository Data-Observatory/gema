"""Client for the Crossref REST API's Works endpoint.

Public, no API key required. Docs: https://api.crossref.org/swagger-ui/index.html
Base URL: https://api.crossref.org/works
"""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

import httpx


class CrossrefClient:
    """Client for Crossref's public Works API (``GET /works/{doi}``)."""

    BASE_URL = "https://api.crossref.org/works"

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        timeout: float = 15.0,
        mailto: str | None = None,
    ) -> None:
        """Initialize. If http_client is None, creates a new httpx.Client.

        Args:
            http_client: Optional pre-configured httpx.Client. If None, a new
                client is created with the given timeout and redirect-following.
            timeout: Request timeout in seconds. Only used when http_client
                is None.
            mailto: Optional contact email included in the User-Agent header —
                Crossref's "polite pool" gets preferential rate limiting for
                requests that identify a contact.
        """
        self._client = http_client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._mailto = mailto

    def get_work(self, doi: str) -> dict[str, Any] | None:
        """Fetch a work record by DOI.

        Args:
            doi: The DOI, with or without a "https://doi.org/" prefix.

        Returns:
            The work's "message" object (Crossref's own record shape), or
            None if the DOI isn't found (404).

        Raises:
            httpx.HTTPStatusError: On any non-404 4xx/5xx response.
        """
        doi = (
            doi.removeprefix("https://doi.org/")
            .removeprefix("http://doi.org/")
            .removeprefix("doi:")
        )
        headers = {
            "User-Agent": (
                f"gema/0.1 (doi-resolver; mailto:{self._mailto})"
                if self._mailto
                else "gema/0.1 (doi-resolver)"
            )
        }
        # quote(safe="/") -- a DOI's own '/' is a real structural part of the
        # identifier (not a path separator to strip), but an unescaped '?' or
        # '#' would be misread as a query string / fragment by URL parsing,
        # silently truncating the path before the request ever reaches
        # Crossref.
        response = self._client.get(f"{self.BASE_URL}/{quote(doi, safe='/')}", headers=headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        message = data.get("message")
        return cast("dict[str, Any]", message) if isinstance(message, dict) else None

    def close(self) -> None:
        """Close the HTTP client if we own it."""
        self._client.close()

    def __enter__(self) -> CrossrefClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
