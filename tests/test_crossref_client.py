"""Tests for enrichers.crossref_client — all network calls mocked."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from metadata_enricher.enrichers.crossref_client import CrossrefClient

MOCK_WORK: dict[str, Any] = {
    "DOI": "10.5880/gfz.2.4.2021.001",
    "title": ["Global Seismic Event Catalog 2021"],
    "publisher": "GFZ Potsdam",
    "author": [{"given": "Jane", "family": "Doe", "affiliation": [{"name": "GFZ Potsdam"}]}],
    "issued": {"date-parts": [[2021, 3, 15]]},
}


def _make_mock_response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = payload
    return mock_response


def _make_client_with_mock_get(mock_response: MagicMock) -> CrossrefClient:
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.get = MagicMock(return_value=mock_response)
    return CrossrefClient(http_client=mock_http)


class TestGetWork:
    def test_returns_message_dict_on_success(self) -> None:
        response = _make_mock_response({"status": "ok", "message": MOCK_WORK})
        client = _make_client_with_mock_get(response)
        result = client.get_work("10.5880/gfz.2.4.2021.001")
        assert result == MOCK_WORK

    def test_returns_none_on_404(self) -> None:
        response = _make_mock_response({}, status_code=404)
        client = _make_client_with_mock_get(response)
        assert client.get_work("10.9999/does-not-exist") is None

    def test_strips_doi_org_prefix(self) -> None:
        response = _make_mock_response({"status": "ok", "message": MOCK_WORK})
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get = MagicMock(return_value=response)
        client = CrossrefClient(http_client=mock_http)
        client.get_work("https://doi.org/10.5880/gfz.2.4.2021.001")
        called_url = mock_http.get.call_args[0][0]
        assert called_url == f"{CrossrefClient.BASE_URL}/10.5880/gfz.2.4.2021.001"

    def test_raises_on_non_404_error(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=mock_response
        )
        client = _make_client_with_mock_get(mock_response)
        with pytest.raises(httpx.HTTPStatusError):
            client.get_work("10.5880/gfz.2.4.2021.001")

    def test_returns_none_when_message_is_not_a_dict(self) -> None:
        response = _make_mock_response({"status": "ok", "message": None})
        client = _make_client_with_mock_get(response)
        assert client.get_work("10.5880/gfz.2.4.2021.001") is None

    def test_mailto_included_in_user_agent(self) -> None:
        response = _make_mock_response({"status": "ok", "message": MOCK_WORK})
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get = MagicMock(return_value=response)
        client = CrossrefClient(http_client=mock_http, mailto="dev@example.org")
        client.get_work("10.5880/gfz.2.4.2021.001")
        headers = mock_http.get.call_args.kwargs["headers"]
        assert "dev@example.org" in headers["User-Agent"]


class TestContextManager:
    def test_closes_owned_client(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        client = CrossrefClient(http_client=mock_http)
        with client:
            pass
        mock_http.close.assert_called_once()
