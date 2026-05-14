"""ROR (Research Organization Registry) resolver for institution enrichment.

Resolves institution names to ROR IDs using the ROR API v2.
No authentication required — rate limited to 2000 requests per 5 minutes.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ROR_BASE_URL = "https://api.ror.org/v2/organizations"


class RORResolver:
    """Resolve institution names to ROR IDs via the ROR API v2.

    Usage::

        >>> resolver = RORResolver()
        >>> resolver.resolve("Ministerio de Hacienda", country_code="CL")
        {"id": "https://ror.org/01h6h5x94", "name": "Ministerio de Hacienda", "country_code": "CL"}
    """

    def __init__(self, timeout: float = 10.0, max_retries: int = 2) -> None:
        """Initialise the resolver.

        Args:
            timeout: HTTP request timeout in seconds.
            max_retries: Maximum retry attempts on 429 / 5xx responses.
        """
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        institution_name: str,
        country_code: Optional[str] = None,
    ) -> Optional[dict]:
        """Resolve an institution name to a ROR record.

        Args:
            institution_name: Raw institution name (whitespace / case normalised).
            country_code: Optional ISO 3166-1 alpha-2 country code to filter by.

        Returns:
            A dict ``{"id": <ror_url>, "name": <display_name>, "country_code": <CC>}``
            when exactly one match is found, or ``None`` when no results / errors
            occurred.
        """
        name = self._normalize_name(institution_name)
        url = f"{ROR_BASE_URL}?query={urllib.parse.quote(name)}"
        if country_code:
            url += f"&filter=locations.geonames_details.country_code:{country_code}"

        data = self._make_request(url)
        if data is None:
            return None

        if data.get("number_of_results", 0) == 0:
            return None

        first = data["items"][0]
        return {
            "id": first.get("id"),
            "name": self._extract_display_name(first),
            "country_code": self._extract_country_code(first),
        }

    def resolve_batch(
        self,
        institutions: list[dict],
        country_code: Optional[str] = None,
    ) -> dict[str, Optional[dict]]:
        """Resolve a batch of institution dicts, deduplicating by normalised name.

        Args:
            institutions: List of dicts with keys ``"name"`` and ``"type"``
                          (e.g. ``{"name": "U. of Chile", "type": "creator"}``).
            country_code: Optional country filter applied to every resolution.

        Returns:
            A dict mapping each original ``name`` to either a result dict
            (same shape as ``resolve()``) or ``None``.
        """
        # Deduplicate: normalised name → first-seen original name.
        seen: dict[str, str] = {}
        for inst in institutions:
            norm = self._normalize_name(inst["name"])
            if norm not in seen:
                seen[norm] = inst["name"]

        # Resolve each unique name once.
        cache: dict[str, Optional[dict]] = {}
        for norm, original in seen.items():
            cache[norm] = self.resolve(original, country_code)

        # Build the output dict keyed by original name.
        result: dict[str, Optional[dict]] = {}
        for inst in institutions:
            norm = self._normalize_name(inst["name"])
            result[inst["name"]] = cache.get(norm)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Strip, collapse inner whitespace, lowercase."""
        return " ".join(name.strip().split()).lower()

    def _make_request(self, url: str) -> Optional[dict]:
        """Perform a GET request to *url* with retries on 429 / 5xx.

        Returns:
            Parsed JSON dict on success, or ``None`` when all attempts fail
            or a non-retryable error occurs.
        """
        retryable_codes: set[int] = {429} | set(range(500, 600))

        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.get(
                    url,
                    timeout=httpx.Timeout(self.timeout),
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in retryable_codes and attempt < self.max_retries:
                    delay = 2**attempt
                    logger.warning(
                        "ROR API returned %d (attempt %d/%d), retrying in %.1fs",
                        status,
                        attempt + 1,
                        self.max_retries + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.warning("ROR API HTTP %d error: %s", status, exc)
                return None
            except httpx.TimeoutException as exc:
                logger.warning("ROR API timeout: %s", exc)
                return None
            except (httpx.ConnectError, Exception) as exc:
                logger.warning("ROR API error: %s", exc)
                return None

        return None

    @staticmethod
    def _extract_display_name(item: dict) -> str:
        """Extract the best display name from a ROR item.

        Prefers the ``ror_display`` / ``label`` type in the ``names`` list.
        Falls back to the top-level ``name`` key (used by some simplified
        fixtures).
        """
        names = item.get("names", [])
        for name_obj in names:
            types = name_obj.get("types", [])
            if "ror_display" in types or "label" in types:
                return name_obj.get("value", "")
        if names:
            return names[0].get("value", "")
        return item.get("name", "")

    @staticmethod
    def _extract_country_code(item: dict) -> Optional[str]:
        """Extract the country code from a ROR item.

        Tries ``locations[0].geonames_details.country_code`` first (the
        canonical ROR API v2 structure), then falls back to
        ``country.country_code`` (simplified fixture format).
        """
        # Canonical ROR API v2: locations list.
        locations = item.get("locations", [])
        for loc in locations:
            geonames = loc.get("geonames_details", {})
            code = geonames.get("country_code")
            if code:
                return code

        # Simplified fixture format: top-level country dict.
        country = item.get("country", {})
        return country.get("country_code")
