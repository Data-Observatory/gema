"""Tests for enrichers.ror_resolver — all network calls mocked."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from enrichers.ror_resolver import RORResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_ror_item(
    ror_id="https://ror.org/01h6h5x94",
    display_name="Ministerio de Hacienda",
    country_code="CL",
    use_canonical=False,
):
    """Build a single ROR API item dict in either canonical or simplified format.

    *canonical* (ROR API v2) uses ``names`` list and ``locations`` list.
    *simplified* (fixture format) uses top-level ``name`` and ``country``.
    """
    if use_canonical:
        return {
            "id": ror_id,
            "names": [
                {
                    "lang": "es",
                    "types": ["ror_display", "label"],
                    "value": display_name,
                },
            ],
            "locations": [
                {
                    "geonames_details": {
                        "country_code": country_code,
                        "country_name": "Chile",
                    }
                },
            ],
        }
    return {
        "id": ror_id,
        "name": display_name,
        "country": {"country_code": country_code, "country_name": "Chile"},
        "locations": [
            {
                "geonames_details": {
                    "country_code": country_code,
                    "country_name": "Chile",
                }
            },
        ],
    }


def _build_ror_response(items, number_of_results=None):
    """Build a complete ROR API v2 response dict."""
    return {
        "number_of_results": number_of_results
        if number_of_results is not None
        else len(items),
        "time_taken": 1,
        "items": items,
    }


def _mock_response(status_code=200, json_data=None):
    """Create a MagicMock httpx.Response with the given status and JSON body."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def resolver():
    return RORResolver(timeout=5.0, max_retries=2)


@pytest.fixture
def single_result_response():
    return _build_ror_response(
        [
            _build_ror_item(
                ror_id="https://ror.org/01h6h5x94",
                display_name="Ministerio de Hacienda",
                country_code="CL",
            ),
        ]
    )


@pytest.fixture
def multi_result_response():
    return _build_ror_response(
        [
            _build_ror_item(
                ror_id="https://ror.org/01h6h5x94",
                display_name="Ministerio de Hacienda",
                country_code="CL",
            ),
            _build_ror_item(
                ror_id="https://ror.org/02q2pz218",
                display_name="Ministerio de Economía",
                country_code="CL",
            ),
        ]
    )


@pytest.fixture
def zero_result_response():
    return _build_ror_response([], number_of_results=0)


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


class TestResolve:
    def test_single_result_returns_dict(self, resolver, single_result_response):
        with patch(
            "httpx.get", return_value=_mock_response(json_data=single_result_response)
        ):
            result = resolver.resolve("Ministerio de Hacienda")

        assert result is not None
        assert result["id"] == "https://ror.org/01h6h5x94"
        assert result["name"] == "Ministerio de Hacienda"
        assert result["country_code"] == "CL"

    def test_multiple_results_returns_first(self, resolver, multi_result_response):
        with patch(
            "httpx.get", return_value=_mock_response(json_data=multi_result_response)
        ):
            result = resolver.resolve("Ministerio")

        assert result is not None
        assert result["id"] == "https://ror.org/01h6h5x94"

    def test_zero_results_returns_none(self, resolver, zero_result_response):
        with patch(
            "httpx.get", return_value=_mock_response(json_data=zero_result_response)
        ):
            result = resolver.resolve("NoSuchInstitution")

        assert result is None

    def test_with_country_filter_adds_filter_param(
        self, resolver, single_result_response
    ):
        with patch(
            "httpx.get", return_value=_mock_response(json_data=single_result_response)
        ) as mock_get:
            resolver.resolve("Ministerio de Hacienda", country_code="CL")

        call_url = mock_get.call_args[0][0]
        assert "query=" in call_url
        assert "filter=locations.geonames_details.country_code:CL" in call_url

    def test_without_country_filter_no_filter_param(
        self, resolver, single_result_response
    ):
        with patch(
            "httpx.get", return_value=_mock_response(json_data=single_result_response)
        ) as mock_get:
            resolver.resolve("Ministerio de Hacienda")

        call_url = mock_get.call_args[0][0]
        assert "filter=" not in call_url

    def test_query_param_is_url_encoded(self, resolver, single_result_response):
        with patch(
            "httpx.get", return_value=_mock_response(json_data=single_result_response)
        ) as mock_get:
            resolver.resolve("Universidad de Chile")

        call_url = mock_get.call_args[0][0]
        assert "query=universidad%20de%20chile" in call_url

    def test_canonical_item_with_names_list(self, resolver):
        canonical_item = _build_ror_item(
            ror_id="https://ror.org/03ya8hzx",
            display_name="Ministerio de Hacienda",
            country_code="CL",
            use_canonical=True,
        )
        response = _build_ror_response([canonical_item])

        with patch("httpx.get", return_value=_mock_response(json_data=response)):
            result = resolver.resolve("Ministerio de Hacienda")

        assert result is not None
        assert result["name"] == "Ministerio de Hacienda"
        assert result["country_code"] == "CL"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestResolveErrors:
    def test_timeout_returns_none(self, resolver):
        with patch("httpx.get", side_effect=httpx.ConnectTimeout("timed out")):
            result = resolver.resolve("Some Institution")

        assert result is None

    def test_http_500_retries_then_returns_none(self, resolver):
        resp_500 = MagicMock(spec=httpx.Response)
        resp_500.status_code = 500
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=resp_500)
        with patch("httpx.get", side_effect=error) as mock_get:
            result = resolver.resolve("Some Institution")

        assert result is None
        # Initial call + 2 retries = 3 total
        assert mock_get.call_count == 3

    def test_http_429_rate_limit_retries_then_returns_none(self, resolver):
        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        error = httpx.HTTPStatusError("429", request=MagicMock(), response=resp_429)
        with patch("httpx.get", side_effect=error) as mock_get:
            result = resolver.resolve("Some Institution")

        assert result is None
        assert mock_get.call_count == 3

    def test_http_404_returns_none_no_retry(self, resolver):
        resp_404 = MagicMock(spec=httpx.Response)
        resp_404.status_code = 404
        error = httpx.HTTPStatusError("404", request=MagicMock(), response=resp_404)
        with patch("httpx.get", side_effect=error) as mock_get:
            result = resolver.resolve("Some Institution")

        assert result is None
        assert mock_get.call_count == 1

    def test_connect_error_returns_none(self, resolver):
        with patch("httpx.get", side_effect=httpx.ConnectError("no network")):
            result = resolver.resolve("Some Institution")

        assert result is None

    def test_invalid_json_returns_none(self, resolver):
        malformed = _mock_response(status_code=200)
        malformed.json.side_effect = json.JSONDecodeError("bad json", "{", 0)

        with patch("httpx.get", return_value=malformed):
            result = resolver.resolve("Some Institution")

        assert result is None


# ---------------------------------------------------------------------------
# resolve_batch
# ---------------------------------------------------------------------------


class TestResolveBatch:
    def test_deduplicates_by_normalized_name(self, resolver, single_result_response):
        institutions = [
            {"name": "  Ministerio  de  Hacienda  ", "type": "creator"},
            {"name": "Ministerio de Hacienda", "type": "publisher"},
            {"name": "ministerio de hacienda", "type": "funder"},
        ]

        with patch(
            "httpx.get", return_value=_mock_response(json_data=single_result_response)
        ) as mock_get:
            results = resolver.resolve_batch(institutions)

        # Only one HTTP call despite three entries.
        assert mock_get.call_count == 1

        # All three keys present.
        assert len(results) == 3
        for name in [
            "  Ministerio  de  Hacienda  ",
            "Ministerio de Hacienda",
            "ministerio de hacienda",
        ]:
            assert name in results
            assert results[name] is not None
            assert results[name]["id"] == "https://ror.org/01h6h5x94"

    def test_returns_mapping_for_all_inputs(self, resolver):
        ok_resp = _build_ror_response(
            [
                _build_ror_item(
                    ror_id="https://ror.org/01h6h5x94",
                    display_name="Ministerio de Hacienda",
                    country_code="CL",
                ),
            ]
        )
        zero_resp = _build_ror_response([], number_of_results=0)

        def _get_side_effect(url, **kwargs):
            if "ministerio" in url:
                return _mock_response(json_data=ok_resp)
            return _mock_response(json_data=zero_resp)

        institutions = [
            {"name": "Ministerio de Hacienda", "type": "creator"},
            {"name": "Unknown Institute", "type": "publisher"},
        ]

        with patch("httpx.get", side_effect=_get_side_effect):
            results = resolver.resolve_batch(institutions)

        assert results["Ministerio de Hacienda"] is not None
        assert results["Ministerio de Hacienda"]["id"] == "https://ror.org/01h6h5x94"
        assert results["Unknown Institute"] is None

    def test_passes_country_code_to_each_resolve(
        self, resolver, single_result_response
    ):
        institutions = [
            {"name": "Ministerio de Hacienda", "type": "creator"},
            {"name": "Ministerio de Economía", "type": "publisher"},
        ]

        with patch(
            "httpx.get", return_value=_mock_response(json_data=single_result_response)
        ) as mock_get:
            resolver.resolve_batch(institutions, country_code="CL")

        for call_args in mock_get.call_args_list:
            url = call_args[0][0]
            assert "filter=locations.geonames_details.country_code:CL" in url


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_strips_and_collapses_spaces(self):
        assert (
            RORResolver._normalize_name("  University  of  Chile  ")
            == "university of chile"
        )

    def test_lowercases(self):
        assert (
            RORResolver._normalize_name("UNIVERSIDAD DE CHILE")
            == "universidad de chile"
        )

    def test_handles_tabs_and_newlines(self):
        assert (
            RORResolver._normalize_name("\tUniversidad\n de \t Chile\n")
            == "universidad de chile"
        )

    def test_handles_empty_string(self):
        assert RORResolver._normalize_name("   ") == ""

    def test_preserves_inner_hyphens(self):
        assert (
            RORResolver._normalize_name("Pontificia Universidad Católica de Chile")
            == "pontificia universidad católica de chile"
        )
