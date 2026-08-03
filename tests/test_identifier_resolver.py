"""Tests for enrichers.identifier_resolver."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from metadata_enricher.enrichers.identifier_resolver import IdentifierResolver

MOCK_ROR_ORG = {
    "id": "https://ror.org/01h6h5x94",
    "names": [
        {"lang": "es", "types": ["ror_display", "label"], "value": "Ministerio de Hacienda"},
    ],
    "external_ids": [
        {"type": "isni", "preferred": "0000 0001 2345 6789", "all": ["0000 0001 2345 6789"]},
    ],
    "relationships": [
        {"id": "https://ror.org/02sevrz47", "label": "Gobierno de Chile", "type": "parent"},
    ],
}

MOCK_ROR_QUERY_ORG = {
    "id": "https://ror.org/01q2pz218",
    "names": [
        {"lang": "es", "types": ["ror_display"], "value": "Universidad de Chile"},
    ],
    "external_ids": [],
    "relationships": [],
}

MOCK_ISNI_RESULT = {
    "isni": "000000040628717X",
    "isni_uri": "https://isni.org/isni/000000040628717X",
    "name": "Ministerio de Hacienda",
    "org_type": "Government",
}


def _make_resolver(
    tmp_path: Path,
    ror_org: dict | None = None,
    ror_query_results: list | None = None,
    isni_results: list | None = None,
    ror_affil_side_effect: Exception | None = None,
    ror_query_side_effect: Exception | None = None,
    isni_side_effect: Exception | None = None,
) -> tuple[IdentifierResolver, MagicMock, MagicMock]:
    ror = MagicMock()
    if ror_affil_side_effect:
        ror.search_affiliation.side_effect = ror_affil_side_effect
    else:
        ror.search_affiliation.return_value = ror_org
    if ror_query_side_effect:
        ror.search_query.side_effect = ror_query_side_effect
    else:
        ror.search_query.return_value = ror_query_results or []
    isni = MagicMock()
    if isni_side_effect:
        isni.search_organizations.side_effect = isni_side_effect
    else:
        isni.search_organizations.return_value = isni_results or []
    resolver = IdentifierResolver(
        ror_client=ror,
        isni_client=isni,
        cache_dir=tmp_path / "test_cache",
    )
    return resolver, ror, isni


# --------------------------------------------------------------------------


class TestResolveRORAffiliation:
    """IdentifierResolver: ROR affiliation endpoint resolution."""

    def test_affiliation_match_returns_identifier_match(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.ror_id == "https://ror.org/01h6h5x94"
        assert result.isni_id == "0000000123456789"
        assert result.org_name == "Ministerio de Hacienda"
        assert result.matched_via == "ror_affiliation"
        assert result.parent_ror_id == "https://ror.org/02sevrz47"
        assert result.parent_name == "Gobierno de Chile"
        assert result.status == "auto"
        assert result.confidence == 1.0

    def test_affiliation_no_chosen_falls_through(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(tmp_path, ror_org=None, ror_query_results=[], isni_results=[])
        result = resolver.resolve("Unknown Org")
        assert result is None


# --------------------------------------------------------------------------


class TestResolveRORQuery:
    """IdentifierResolver: ROR query endpoint with fuzzy matching."""

    def test_query_fuzzy_match_returns_result(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[MOCK_ROR_QUERY_ORG],
        )
        result = resolver.resolve("Universidad de Chile")
        assert result is not None
        assert result.ror_id == "https://ror.org/01q2pz218"
        assert result.org_name == "Universidad de Chile"
        assert result.matched_via == "ror_query_fuzzy"

    def test_query_below_threshold_falls_through(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[MOCK_ROR_QUERY_ORG],
            isni_results=[],
        )
        result = resolver.resolve("Completely Different Organization Name")
        assert result is None


# --------------------------------------------------------------------------


class TestResolveISNI:
    """IdentifierResolver: ISNI SRU fallback with fuzzy matching."""

    def test_isni_match_returns_result(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[],
            isni_results=[MOCK_ISNI_RESULT],
        )
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.isni_id == "000000040628717X"
        assert result.matched_via == "isni_sru"

    def test_isni_no_results_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _ = _make_resolver(tmp_path, ror_org=None, isni_results=[])
        result = resolver.resolve("Nonexistent Organization")
        assert result is None


# --------------------------------------------------------------------------


class TestCaching:
    """IdentifierResolver: disk cache behavior."""

    def test_cache_hit_avoids_network(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        resolver.resolve("Ministerio de Hacienda")
        assert ror.search_affiliation.call_count == 1
        resolver.resolve("Ministerio de Hacienda")
        assert ror.search_affiliation.call_count == 1

    def test_negative_result_cached(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(tmp_path, ror_org=None, isni_results=[])
        resolver.resolve("Unknown Org Name")
        first_calls = ror.search_affiliation.call_count
        resolver.resolve("Unknown Org Name")
        assert ror.search_affiliation.call_count == first_calls

    def test_different_names_not_cached_together(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        resolver.resolve("Ministerio de Hacienda")
        resolver.resolve("Universidad de Chile")
        assert ror.search_affiliation.call_count == 2


# --------------------------------------------------------------------------


class TestErrorHandling:
    """IdentifierResolver: graceful error handling."""

    def test_ror_affiliation_exception_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _ = _make_resolver(
            tmp_path,
            ror_affil_side_effect=RuntimeError("network error"),
            ror_query_results=[],
            isni_results=[],
        )
        result = resolver.resolve("Test Org")
        assert result is None

    def test_ror_query_exception_falls_through_to_isni(self, tmp_path: Path) -> None:
        resolver, _, isni = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_side_effect=RuntimeError("query error"),
            isni_results=[MOCK_ISNI_RESULT],
        )
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.matched_via == "isni_sru"
        assert isni.search_organizations.called

    def test_isni_exception_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[],
            isni_side_effect=RuntimeError("isni error"),
        )
        result = resolver.resolve("Test Org")
        assert result is None

    def test_all_fail_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _ = _make_resolver(
            tmp_path,
            ror_affil_side_effect=RuntimeError("err1"),
            ror_query_side_effect=RuntimeError("err2"),
            isni_side_effect=RuntimeError("err3"),
        )
        result = resolver.resolve("Test Org")
        assert result is None


# --------------------------------------------------------------------------


class TestEdgeCases:
    """IdentifierResolver: edge cases and lifecycle."""

    def test_empty_name_returns_none(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        assert resolver.resolve("") is None
        assert not ror.search_affiliation.called

    def test_whitespace_name_returns_none(self, tmp_path: Path) -> None:
        resolver, ror, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        assert resolver.resolve("   ") is None
        assert not ror.search_affiliation.called

    def test_context_manager_closes(self, tmp_path: Path) -> None:
        ror = MagicMock()
        isni = MagicMock()
        with IdentifierResolver(
            ror_client=ror, isni_client=isni, cache_dir=tmp_path / "cm_cache"
        ):
            pass
        ror.close.assert_called_once()
        isni.close.assert_called_once()
