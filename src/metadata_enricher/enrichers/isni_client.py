"""Client for the ISNI SRU (Search/Retrieve via URL) API.

Searches organizations via the OCLC ISNI SRU endpoint, parses the XML
response, and extracts ISNI identifiers. Uses ``httpx`` for HTTP and the
stdlib ``xml.etree.ElementTree`` for parsing — no third-party XML deps.
"""

from __future__ import annotations

import logging
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# SRU response wrapper namespace (prefix "srw:"). The ISNI metadata content
# inside <srw:recordData>/<responseRecord> has NO namespace.
_SRU_NS = {"srw": "http://www.loc.gov/zing/srw/"}


class ISNIClient:
    """Client for the ISNI SRU (Search/Retrieve via URL) API.

    Docs: https://wiki.lyrasis.org/display/ISNI/ISNI+SRU+API
    Base URL: http://isni.oclc.org/sru/DB=1.2/

    The free public endpoint returns XML with ISNI records for
    organizations. Use ``pica.nw`` for keyword search.
    """

    BASE_URL = "http://isni.oclc.org/sru/DB=1.2/"
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize. Creates a new ``httpx.Client`` if none provided.

        Args:
            http_client: Optional pre-configured client (e.g. for testing).
                         If provided, ``timeout`` is ignored.
            timeout: Request timeout in seconds (default 30.0). Used only
                     when ``http_client`` is ``None``.
        """
        self._client = http_client or httpx.Client(
            timeout=timeout, follow_redirects=True
        )

    def search_organizations(
        self, keywords: str, max_records: int = 5
    ) -> list[dict[str, str | None]]:
        """Search for organizations by keywords using the ``pica.nw`` index.

        Args:
            keywords: Organization name keywords (e.g.
                      ``"massachusetts institute technology"``).
            max_records: Maximum results to return (default 5).

        Returns:
            List of dicts with keys: ``"isni"``, ``"isni_uri"``, ``"name"``,
            ``"org_type"``. Each value is a string or ``None`` if not found
            in the record. Returns an empty list if no results or on ANY
            error (network, HTTP status, XML parse) — never raises.
        """
        params = {
            "query": f'pica.nw = "{keywords}"',
            "operation": "searchRetrieve",
            "recordSchema": "isni-b",
            "maximumRecords": str(max_records),
        }
        try:
            xml_bytes = self._request(params)
        except httpx.HTTPError as exc:
            logger.warning("ISNI SRU request failed: %s", exc)
            return []
        return parse_isni_response(xml_bytes)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> ISNIClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, params: dict[str, str]) -> bytes:
        """Execute a GET request to the ISNI SRU endpoint.

        Args:
            params: Query parameters for the SRU request.

        Returns:
            Raw response bytes.

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses.
            httpx.HTTPError: On network/transport errors.
        """
        headers = {"User-Agent": "metagen/0.1 (identifier-resolver)"}
        response = self._client.get(
            self.BASE_URL, params=params, headers=headers
        )
        response.raise_for_status()
        return response.content


def parse_isni_response(xml_bytes: bytes) -> list[dict[str, str | None]]:
    """Parse an ISNI SRU XML response into a list of organization dicts.

    The XML structure:
    - SRU wrapper uses namespace ``http://www.loc.gov/zing/srw/``
      (prefix ``srw:``).
    - The ``responseRecord`` / ISNI metadata content inside
      ``<srw:recordData>`` has NO namespace.

    Extracts from each record:
    - ``isni``: from ``<isniUnformatted>`` (16-digit string, may end in X).
    - ``isni_uri``: ``"https://isni.org/isni/" + isni``.
    - ``name``: from ``<mainName>`` inside ``<organisationName>``.
    - ``org_type``: from ``<organisationType>``.

    Args:
        xml_bytes: Raw XML response bytes from the ISNI SRU API.

    Returns:
        List of dicts, each with keys ``"isni"``, ``"isni_uri"``, ``"name"``,
        ``"org_type"``. On parse error, logs a warning and returns ``[]``.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("Failed to parse ISNI SRU XML: %s", exc)
        return []

    results: list[dict[str, str | None]] = []
    for record in root.findall(".//srw:record", _SRU_NS):
        record_data = record.find("srw:recordData", _SRU_NS)
        if record_data is None:
            continue

        # ISNI metadata content has NO namespace — search without the NS map.
        isni = _text_or_none(record_data.find(".//isniUnformatted"))
        name = _text_or_none(record_data.find(".//mainName"))
        org_type = _text_or_none(record_data.find(".//organisationType"))

        results.append(
            {
                "isni": isni,
                "isni_uri": f"https://isni.org/isni/{isni}" if isni else None,
                "name": name,
                "org_type": org_type,
            }
        )

    return results


def _text_or_none(elem: ET.Element | None) -> str | None:
    """Return stripped text of ``elem``, or ``None`` if missing/empty."""
    if elem is None or elem.text is None:
        return None
    text = elem.text.strip()
    return text or None
