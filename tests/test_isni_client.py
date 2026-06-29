"""Tests for enrichers.isni_client — all network calls mocked."""

from __future__ import annotations

from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import httpx

from metadata_enricher.enrichers.isni_client import (
    ISNIClient,
    _text_or_none,
    parse_isni_response,
)


# ---------------------------------------------------------------------------
# Mock ISNI SRU XML data (namespace: http://www.loc.gov/zing/srw/, prefix srw:)
# ---------------------------------------------------------------------------

SINGLE_RECORD_XML: bytes = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">\n'
    b"  <srw:version>1.1</srw:version>\n"
    b"  <srw:numberOfRecords>1</srw:numberOfRecords>\n"
    b"  <srw:records>\n"
    b"    <srw:record>\n"
    b"      <srw:recordSchema>isni-b</srw:recordSchema>\n"
    b"      <srw:recordPacking>xml</srw:recordPacking>\n"
    b"      <srw:recordData>\n"
    b"        <responseRecord>\n"
    b"          <ISNIAssigned>\n"
    b"            <isniUnformatted>0000000122977777</isniUnformatted>\n"
    b"            <organisationName>\n"
b"              <mainName>Instituto Nacional de Estad&#237;sticas</mainName>\n"
b"            </organisationName>\n"
b"            <organisationType>org</organisationType>\n"
b"          </ISNIAssigned>\n"
b"        </responseRecord>\n"
b"      </srw:recordData>\n"
b"    </srw:record>\n"
b"  </srw:records>\n"
b"</srw:searchRetrieveResponse>\n"
)

MULTI_RECORD_XML: bytes = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">\n'
    b"  <srw:numberOfRecords>2</srw:numberOfRecords>\n"
    b"  <srw:records>\n"
    b"    <srw:record>\n"
    b"      <srw:recordData>\n"
    b"        <responseRecord>\n"
    b"          <ISNIAssigned>\n"
    b"            <isniUnformatted>0000000122977777</isniUnformatted>\n"
    b"            <organisationName>\n"
    b"              <mainName>Instituto Nacional de Estad&#237;sticas</mainName>\n"
    b"            </organisationName>\n"
    b"            <organisationType>org</organisationType>\n"
    b"          </ISNIAssigned>\n"
    b"        </responseRecord>\n"
    b"      </srw:recordData>\n"
    b"    </srw:record>\n"
    b"    <srw:record>\n"
    b"      <srw:recordData>\n"
    b"        <responseRecord>\n"
    b"          <ISNIAssigned>\n"
    b"            <isniUnformatted>0000000219221234</isniUnformatted>\n"
    b"            <organisationName>\n"
    b"              <mainName>Ministry of Finance</mainName>\n"
    b"            </organisationName>\n"
    b"            <organisationType>gov</organisationType>\n"
    b"          </ISNIAssigned>\n"
    b"        </responseRecord>\n"
    b"      </srw:recordData>\n"
    b"    </srw:record>\n"
    b"  </srw:records>\n"
    b"</srw:searchRetrieveResponse>\n"
)

EMPTY_RECORDS_XML: bytes = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">\n'
    b"  <srw:numberOfRecords>0</srw:numberOfRecords>\n"
    b"  <srw:records />\n"
    b"</srw:searchRetrieveResponse>\n"
)

MISSING_FIELDS_XML: bytes = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">\n'
    b"  <srw:numberOfRecords>1</srw:numberOfRecords>\n"
    b"  <srw:records>\n"
    b"    <srw:record>\n"
    b"      <srw:recordData>\n"
    b"        <responseRecord>\n"
    b"          <ISNIAssigned>\n"
    b"            <isniUnformatted>0000000122977777</isniUnformatted>\n"
    b"            <organisationType>org</organisationType>\n"
    b"          </ISNIAssigned>\n"
    b"        </responseRecord>\n"
    b"      </srw:recordData>\n"
    b"    </srw:record>\n"
    b"  </srw:records>\n"
    b"</srw:searchRetrieveResponse>\n"
)

NO_ISNI_XML: bytes = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">\n'
    b"  <srw:records>\n"
    b"    <srw:record>\n"
    b"      <srw:recordData>\n"
    b"        <responseRecord>\n"
    b"          <ISNIAssigned>\n"
    b"            <organisationName>\n"
    b"              <mainName>No ISNI Org</mainName>\n"
    b"            </organisationName>\n"
    b"            <organisationType>org</organisationType>\n"
    b"          </ISNIAssigned>\n"
    b"        </responseRecord>\n"
    b"      </srw:recordData>\n"
    b"    </srw:record>\n"
    b"  </srw:records>\n"
    b"</srw:searchRetrieveResponse>\n"
)

INVALID_XML: bytes = b"not valid xml"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_response(content: bytes) -> MagicMock:
    """Build a MagicMock of httpx.Response returning the given content."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_response.content = content
    return mock_response


def _make_client_with_mock_get(mock_response: MagicMock) -> ISNIClient:
    """Build an ISNIClient whose inner httpx.Client.get returns mock_response."""
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.get = MagicMock(return_value=mock_response)
    return ISNIClient(http_client=mock_http)


# ---------------------------------------------------------------------------
# search_organizations
# ---------------------------------------------------------------------------


class TestSearchOrganizations:
    """ISNIClient.search_organizations — keyword search via SRU pica.nw."""

    def test_search_returns_parsed_records(self) -> None:
        mock_response = _make_mock_response(SINGLE_RECORD_XML)
        client = _make_client_with_mock_get(mock_response)

        result = client.search_organizations("Instituto Nacional")

        assert len(result) == 1
        assert result[0]["isni"] == "0000000122977777"
        assert result[0]["name"] == "Instituto Nacional de Estadísticas"
        assert result[0]["org_type"] == "org"
        assert result[0]["isni_uri"] == "https://isni.org/isni/0000000122977777"

    def test_search_passes_pica_nw_query(self) -> None:
        mock_response = _make_mock_response(SINGLE_RECORD_XML)
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get = MagicMock(return_value=mock_response)
        client = ISNIClient(http_client=mock_http)

        client.search_organizations("test org")

        call_kwargs = mock_http.get.call_args
        params: dict[str, str] = call_kwargs.kwargs.get("params") or {}
        assert params.get("query") == 'pica.nw = "test org"'

    def test_search_empty_response(self) -> None:
        mock_response = _make_mock_response(EMPTY_RECORDS_XML)
        client = _make_client_with_mock_get(mock_response)

        result = client.search_organizations("ghost")

        assert result == []

    def test_search_http_error_returns_empty(self) -> None:
        mock_request = MagicMock()
        mock_resp = MagicMock()
        exc = httpx.HTTPStatusError(
            "500 Server Error", request=mock_request, response=mock_resp
        )
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get = MagicMock(side_effect=exc)
        client = ISNIClient(http_client=mock_http)

        result = client.search_organizations("test")

        assert result == []

    def test_search_network_error_returns_empty(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get = MagicMock(side_effect=httpx.HTTPError("Connection refused"))
        client = ISNIClient(http_client=mock_http)

        result = client.search_organizations("test")

        assert result == []

    def test_search_max_records_param(self) -> None:
        mock_response = _make_mock_response(SINGLE_RECORD_XML)
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get = MagicMock(return_value=mock_response)
        client = ISNIClient(http_client=mock_http)

        client.search_organizations("test", max_records=10)

        call_kwargs = mock_http.get.call_args
        params: dict[str, str] = call_kwargs.kwargs.get("params") or {}
        assert params.get("maximumRecords") == "10"


# ---------------------------------------------------------------------------
# parse_isni_response
# ---------------------------------------------------------------------------


class TestParseIsniResponse:
    """parse_isni_response — SRU XML parsing into organisation dicts."""

    def test_parse_single_record(self) -> None:
        result = parse_isni_response(SINGLE_RECORD_XML)

        assert len(result) == 1
        assert result[0]["isni"] == "0000000122977777"
        assert result[0]["isni_uri"] == "https://isni.org/isni/0000000122977777"
        assert result[0]["name"] == "Instituto Nacional de Estadísticas"
        assert result[0]["org_type"] == "org"

    def test_parse_multiple_records(self) -> None:
        result = parse_isni_response(MULTI_RECORD_XML)

        assert len(result) == 2
        assert result[0]["isni"] == "0000000122977777"
        assert result[0]["name"] == "Instituto Nacional de Estadísticas"
        assert result[1]["isni"] == "0000000219221234"
        assert result[1]["name"] == "Ministry of Finance"
        assert result[1]["org_type"] == "gov"

    def test_parse_empty_records(self) -> None:
        result = parse_isni_response(EMPTY_RECORDS_XML)

        assert result == []

    def test_parse_invalid_xml_returns_empty(self) -> None:
        result = parse_isni_response(INVALID_XML)

        assert result == []

    def test_parse_missing_fields(self) -> None:
        result = parse_isni_response(MISSING_FIELDS_XML)

        assert len(result) == 1
        assert result[0]["isni"] == "0000000122977777"
        assert result[0]["name"] is None
        assert result[0]["org_type"] == "org"

    def test_parse_isni_uri_construction(self) -> None:
        result = parse_isni_response(SINGLE_RECORD_XML)

        assert result[0]["isni_uri"] == "https://isni.org/isni/0000000122977777"

    def test_parse_none_isni_returns_none_uri(self) -> None:
        result = parse_isni_response(NO_ISNI_XML)

        assert len(result) == 1
        assert result[0]["isni"] is None
        assert result[0]["isni_uri"] is None


# ---------------------------------------------------------------------------
# _text_or_none
# ---------------------------------------------------------------------------


class TestTextOrNone:
    """_text_or_none — stripped text extraction helper."""

    def test_returns_stripped_text(self) -> None:
        elem = ET.fromstring("<elem>  hello  </elem>")
        assert _text_or_none(elem) == "hello"

    def test_returns_none_for_no_text(self) -> None:
        elem = ET.fromstring("<elem></elem>")
        assert _text_or_none(elem) is None

    def test_returns_none_for_whitespace_only(self) -> None:
        elem = ET.fromstring("<elem>   </elem>")
        assert _text_or_none(elem) is None

    def test_returns_none_for_none_elem(self) -> None:
        assert _text_or_none(None) is None


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    """ISNIClient context-manager and close behavior."""

    def test_context_manager_closes_client(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        with ISNIClient(http_client=mock_http):
            pass
        mock_http.close.assert_called_once()

    def test_close_invokes_underlying_close(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        client = ISNIClient(http_client=mock_http)
        client.close()
        mock_http.close.assert_called_once()
