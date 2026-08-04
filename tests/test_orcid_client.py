"""Tests for enrichers.orcid_client — all network calls mocked."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx

from metadata_enricher.enrichers.orcid_client import ORCIDClient

MOCK_TOKEN_RESPONSE = {"access_token": "mock-token-abc", "token_type": "bearer", "expires_in": 631138518}

MOCK_SEARCH_RESPONSE_ONE_HIT = {
    "num-found": 1,
    "result": [
        {"orcid-identifier": {"uri": "https://orcid.org/0000-0002-1825-0097", "path": "0000-0002-1825-0097", "host": "orcid.org"}}
    ],
}

MOCK_SEARCH_RESPONSE_EMPTY = {"num-found": 0, "result": []}


def _make_mock_response(payload: dict[str, Any]) -> MagicMock:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = payload
    return mock_response


def _make_client(
    token_payload: dict[str, Any] | None = MOCK_TOKEN_RESPONSE,
    search_payload: dict[str, Any] | None = MOCK_SEARCH_RESPONSE_ONE_HIT,
    client_id: str | None = "fake-id",
    client_secret: str | None = "fake-secret",
) -> tuple[ORCIDClient, MagicMock]:
    mock_http = MagicMock(spec=httpx.Client)
    responses = []
    if token_payload is not None:
        responses.append(_make_mock_response(token_payload))
    mock_http.post = MagicMock(side_effect=lambda *a, **kw: responses.pop(0))
    if search_payload is not None:
        mock_http.get = MagicMock(return_value=_make_mock_response(search_payload))
    client = ORCIDClient(http_client=mock_http, client_id=client_id, client_secret=client_secret)
    return client, mock_http


class TestEnabled:
    def test_enabled_with_credentials(self) -> None:
        client = ORCIDClient(http_client=MagicMock(spec=httpx.Client), client_id="a", client_secret="b")
        assert client.enabled is True

    def test_disabled_without_credentials(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("ORCID_CLIENT_ID", raising=False)
        monkeypatch.delenv("ORCID_CLIENT_SECRET", raising=False)
        client = ORCIDClient(http_client=MagicMock(spec=httpx.Client))
        assert client.enabled is False


class TestSearchPerson:
    def test_missing_credentials_returns_empty_without_network_call(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("ORCID_CLIENT_ID", raising=False)
        monkeypatch.delenv("ORCID_CLIENT_SECRET", raising=False)
        mock_http = MagicMock(spec=httpx.Client)
        client = ORCIDClient(http_client=mock_http)
        result = client.search_person("Jane", "Roe")
        assert result == {"num_found": 0, "orcids": []}
        assert not mock_http.post.called
        assert not mock_http.get.called

    def test_single_hit_returns_one_orcid(self) -> None:
        client, mock_http = _make_client()
        result = client.search_person("Jane", "Roe")
        assert result == {"num_found": 1, "orcids": ["0000-0002-1825-0097"]}

    def test_query_includes_given_and_family_name(self) -> None:
        client, mock_http = _make_client()
        client.search_person("Jane", "Roe")
        call_kwargs = mock_http.get.call_args
        query = call_kwargs.kwargs["params"]["q"]
        assert 'family-name:"Roe"' in query
        assert 'given-names:"Jane"' in query

    def test_query_includes_affiliation_when_given(self) -> None:
        client, mock_http = _make_client()
        client.search_person("Jane", "Roe", affiliation_org_name="Universidad de Chile")
        query = mock_http.get.call_args.kwargs["params"]["q"]
        assert 'affiliation-org-name:"Universidad de Chile"' in query

    def test_no_hits_returns_empty(self) -> None:
        client, _ = _make_client(search_payload=MOCK_SEARCH_RESPONSE_EMPTY)
        result = client.search_person("Nobody", "Real")
        assert result == {"num_found": 0, "orcids": []}

    def test_token_fetch_failure_returns_empty(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.post = MagicMock(side_effect=httpx.HTTPError("token endpoint down"))
        client = ORCIDClient(http_client=mock_http, client_id="a", client_secret="b")
        result = client.search_person("Jane", "Roe")
        assert result == {"num_found": 0, "orcids": []}
        assert not mock_http.get.called

    def test_token_fetch_failure_is_cached_not_retried(self) -> None:
        """A failed token fetch must not be retried on every subsequent search —
        that would mean one down OAuth endpoint costs a network round-trip per
        creator/publisher in a resource, every time."""
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.post = MagicMock(side_effect=httpx.HTTPError("token endpoint down"))
        client = ORCIDClient(http_client=mock_http, client_id="a", client_secret="b")
        client.search_person("Jane", "Roe")
        client.search_person("John", "Smith")
        assert mock_http.post.call_count == 1
        assert not mock_http.get.called

    def test_token_fetched_once_and_reused(self) -> None:
        client, mock_http = _make_client()
        client.search_person("Jane", "Roe")
        client.search_person("Jane", "Roe")
        assert mock_http.post.call_count == 1
        assert mock_http.get.call_count == 2

    def test_search_http_error_returns_empty(self) -> None:
        client, mock_http = _make_client()
        mock_http.get.side_effect = httpx.HTTPError("search down")
        result = client.search_person("Jane", "Roe")
        assert result == {"num_found": 0, "orcids": []}


class TestClientLifecycle:
    def test_context_manager_closes_client(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        with ORCIDClient(http_client=mock_http):
            pass
        mock_http.close.assert_called_once()
