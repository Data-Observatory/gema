"""Tests for enrichers.ror_client — all network calls mocked."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx

from metadata_enricher.enrichers.ror_client import (
    RORClient,
    escape_query,
    extract_isni,
    extract_parent,
    get_display_name,
)


# ---------------------------------------------------------------------------
# ROR v2 mock data (inline — conftest fixture is v1 format)
# ---------------------------------------------------------------------------

MOCK_ROR_V2_ORG: dict[str, Any] = {
    "id": "https://ror.org/01h6h5x94",
    "names": [
        {"lang": "es", "types": ["ror_display", "label"], "value": "Ministerio de Hacienda"},
        {"lang": "en", "types": ["label"], "value": "Ministry of Finance"},
        {"lang": None, "types": ["acronym"], "value": "MINHAC"},
    ],
    "types": ["Government"],
    "status": "active",
    "established": 1817,
    "external_ids": [
        {"type": "isni", "preferred": "0000 0001 2345 6789", "all": ["0000 0001 2345 6789"]},
        {"type": "grid", "preferred": "grid.12345", "all": ["grid.12345"]},
    ],
    "relationships": [
        {"id": "https://ror.org/02sevrz47", "label": "Gobierno de Chile", "type": "parent"},
        {"id": "https://ror.org/03dz0k314", "label": "Some Child", "type": "child"},
    ],
}

MOCK_ROR_V2_AFFILIATION_RESPONSE: dict[str, Any] = {
    "items": [
        {
            "chosen": True,
            "matching_type": "SINGLE SEARCH",
            "score": 1.0,
            "substring": "Ministerio de Hacienda",
            "organization": MOCK_ROR_V2_ORG,
        },
        {
            "chosen": False,
            "matching_type": "SINGLE SEARCH",
            "score": 0.85,
            "organization": {**MOCK_ROR_V2_ORG, "id": "https://ror.org/02sevrz47"},
        },
    ],
}

MOCK_ROR_V2_QUERY_RESPONSE: dict[str, Any] = {
    "items": [MOCK_ROR_V2_ORG],
    "number_of_results": 1,
    "time_taken": 42,
}


def _make_mock_response(payload: dict[str, Any]) -> MagicMock:
    """Build a MagicMock of httpx.Response returning the given payload."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = payload
    return mock_response


def _make_client_with_mock_get(
    mock_response: MagicMock,
) -> RORClient:
    """Build a RORClient whose inner httpx.Client.get returns mock_response."""
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.get = MagicMock(return_value=mock_response)
    return RORClient(http_client=mock_http)


# ---------------------------------------------------------------------------
# search_affiliation
# ---------------------------------------------------------------------------


class TestSearchAffiliation:
    """RORClient.search_affiliation — ?affiliation= endpoint."""

    def test_affiliation_chosen_true_returns_org(self) -> None:
        mock_response = _make_mock_response(MOCK_ROR_V2_AFFILIATION_RESPONSE)
        client = _make_client_with_mock_get(mock_response)

        result = client.search_affiliation("Ministerio de Hacienda")

        assert result is not None
        assert result["id"] == "https://ror.org/01h6h5x94"

    def test_affiliation_no_chosen_returns_none(self) -> None:
        payload = {
            "items": [
                {
                    "chosen": False,
                    "score": 0.9,
                    "organization": MOCK_ROR_V2_ORG,
                }
            ]
        }
        mock_response = _make_mock_response(payload)
        client = _make_client_with_mock_get(mock_response)

        result = client.search_affiliation("Some Org")

        assert result is None

    def test_affiliation_empty_items_returns_none(self) -> None:
        mock_response = _make_mock_response({"items": []})
        client = _make_client_with_mock_get(mock_response)

        result = client.search_affiliation("Ghost University")

        assert result is None

    def test_affiliation_passes_affiliation_param(self) -> None:
        mock_response = _make_mock_response(MOCK_ROR_V2_AFFILIATION_RESPONSE)
        client = _make_client_with_mock_get(mock_response)

        client.search_affiliation("Dept of Biology, Harvard University")

        assert client._client.get.called  # type: ignore[attr-defined]
        call_kwargs = client._client.get.call_args  # type: ignore[attr-defined]
        params = call_kwargs.kwargs.get("params") or {}
        assert params.get("affiliation") == "Dept of Biology, Harvard University"


# ---------------------------------------------------------------------------
# search_query
# ---------------------------------------------------------------------------


class TestSearchQuery:
    """RORClient.search_query — ?query= endpoint."""

    def test_query_returns_org_list(self) -> None:
        mock_response = _make_mock_response(MOCK_ROR_V2_QUERY_RESPONSE)
        client = _make_client_with_mock_get(mock_response)

        result = client.search_query("Ministerio de Hacienda")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == "https://ror.org/01h6h5x94"

    def test_query_empty_results(self) -> None:
        mock_response = _make_mock_response({"items": [], "number_of_results": 0})
        client = _make_client_with_mock_get(mock_response)

        result = client.search_query("Nonexistent University")

        assert result == []

    def test_query_escapes_reserved_chars(self) -> None:
        mock_response = _make_mock_response({"items": []})
        client = _make_client_with_mock_get(mock_response)

        client.search_query("MIT (Massachusetts)")

        assert client._client.get.called  # type: ignore[attr-defined]
        call_kwargs = client._client.get.call_args  # type: ignore[attr-defined]
        params = call_kwargs.kwargs.get("params") or {}
        assert params.get("query") == "MIT \\(Massachusetts\\)"

    def test_query_passes_limit_param(self) -> None:
        mock_response = _make_mock_response({"items": []})
        client = _make_client_with_mock_get(mock_response)

        client.search_query("Harvard", limit=10)

        call_kwargs = client._client.get.call_args  # type: ignore[attr-defined]
        params = call_kwargs.kwargs.get("params") or {}
        assert params.get("limit") == "10"


# ---------------------------------------------------------------------------
# extract_isni
# ---------------------------------------------------------------------------


class TestExtractISNI:
    """extract_isni — ISNI normalization from ROR v2 external_ids."""

    def test_extract_isni_from_preferred(self) -> None:
        assert extract_isni(MOCK_ROR_V2_ORG) == "0000000123456789"

    def test_extract_isni_falls_back_to_all(self) -> None:
        org = {
            "external_ids": [
                {"type": "isni", "preferred": None, "all": ["0000 0001 9999 8888"]},
            ]
        }
        assert extract_isni(org) == "0000000199998888"

    def test_extract_isni_no_isni_entry(self) -> None:
        org = {
            "external_ids": [
                {"type": "grid", "preferred": "grid.12345", "all": ["grid.12345"]},
            ]
        }
        assert extract_isni(org) is None

    def test_extract_isni_removes_spaces(self) -> None:
        org = {
            "external_ids": [
                {"type": "isni", "preferred": "0000 0001 0726 5157", "all": []},
            ]
        }
        assert extract_isni(org) == "0000000107265157"

    def test_extract_isni_no_external_ids(self) -> None:
        assert extract_isni({}) is None

    def test_extract_isni_entry_with_empty_values(self) -> None:
        org = {
            "external_ids": [
                {"type": "isni", "preferred": None, "all": []},
            ]
        }
        assert extract_isni(org) is None


# ---------------------------------------------------------------------------
# extract_parent
# ---------------------------------------------------------------------------


class TestExtractParent:
    """extract_parent — parent organization from ROR v2 relationships."""

    def test_extract_parent_found(self) -> None:
        parent_id, parent_name = extract_parent(MOCK_ROR_V2_ORG)

        assert parent_id == "https://ror.org/02sevrz47"
        assert parent_name == "Gobierno de Chile"

    def test_extract_parent_not_found(self) -> None:
        org = {
            "relationships": [
                {"id": "https://ror.org/abc", "label": "Child Org", "type": "child"},
            ]
        }
        assert extract_parent(org) == (None, None)

    def test_extract_parent_multiple_relationships(self) -> None:
        parent_id, parent_name = extract_parent(MOCK_ROR_V2_ORG)

        assert parent_id == "https://ror.org/02sevrz47"
        assert parent_name == "Gobierno de Chile"

    def test_extract_parent_no_relationships(self) -> None:
        assert extract_parent({}) == (None, None)


# ---------------------------------------------------------------------------
# get_display_name
# ---------------------------------------------------------------------------


class TestGetDisplayName:
    """get_display_name — display name extraction from ROR v2 names array."""

    def test_display_name_from_ror_display_type(self) -> None:
        assert get_display_name(MOCK_ROR_V2_ORG) == "Ministerio de Hacienda"

    def test_display_name_fallback_to_first(self) -> None:
        org = {
            "names": [
                {"lang": "en", "types": ["label"], "value": "Ministry of Finance"},
            ]
        }
        assert get_display_name(org) == "Ministry of Finance"

    def test_display_name_empty_names(self) -> None:
        assert get_display_name({"names": []}) == ""

    def test_display_name_no_names_key(self) -> None:
        assert get_display_name({}) == ""


# ---------------------------------------------------------------------------
# escape_query
# ---------------------------------------------------------------------------


class TestEscapeQuery:
    """escape_query — Elasticsearch reserved-char escaping."""

    def test_escape_simple_name(self) -> None:
        assert escape_query("Harvard University") == "Harvard University"

    def test_escape_reserved_chars(self) -> None:
        escaped = escape_query("MIT (Massachusetts) + Energy")
        assert escaped == "MIT \\(Massachusetts\\) \\+ Energy"

    def test_escape_backslash(self) -> None:
        assert escape_query("a\\b") == "a\\\\b"

    def test_escape_quotation_mark(self) -> None:
        assert escape_query('"quoted"') == '\\"quoted\\"'

    def test_escape_colon_and_question(self) -> None:
        assert escape_query("what: now?") == "what\\: now\\?"

    def test_escape_empty_string(self) -> None:
        assert escape_query("") == ""


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    """RORClient context-manager and close behavior."""

    def test_context_manager_closes_client(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        with RORClient(http_client=mock_http):
            pass
        mock_http.close.assert_called_once()

    def test_close_invokes_underlying_close(self) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        client = RORClient(http_client=mock_http)
        client.close()
        mock_http.close.assert_called_once()
