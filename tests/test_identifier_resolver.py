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

MOCK_ROR_QUERY_ORG_AR = {
    **MOCK_ROR_QUERY_ORG,
    "id": "https://ror.org/aaaa1111",
    "locations": [{"geonames_details": {"country_code": "AR"}}],
}
MOCK_ROR_QUERY_ORG_CL = {
    **MOCK_ROR_QUERY_ORG,
    "id": "https://ror.org/bbbb2222",
    "locations": [{"geonames_details": {"country_code": "CL"}}],
}


def _make_resolver(
    tmp_path: Path,
    ror_org: dict | None = None,
    ror_query_results: list | None = None,
    isni_results: list | None = None,
    ror_affil_side_effect: Exception | None = None,
    ror_query_side_effect: Exception | None = None,
    isni_side_effect: Exception | None = None,
    orcid_result: dict | None = None,
    orcid_side_effect: Exception | None = None,
) -> tuple[IdentifierResolver, MagicMock, MagicMock, MagicMock]:
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
    orcid = MagicMock()
    if orcid_side_effect:
        orcid.search_person.side_effect = orcid_side_effect
    else:
        orcid.search_person.return_value = orcid_result or {"num_found": 0, "orcids": []}
    resolver = IdentifierResolver(
        ror_client=ror,
        isni_client=isni,
        orcid_client=orcid,
        cache_dir=tmp_path / "test_cache",
    )
    return resolver, ror, isni, orcid


# --------------------------------------------------------------------------


class TestResolveRORAffiliation:
    """IdentifierResolver: ROR affiliation endpoint resolution."""

    def test_affiliation_match_returns_identifier_match(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
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
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=None, ror_query_results=[], isni_results=[])
        result = resolver.resolve("Unknown Org")
        assert result is None


# --------------------------------------------------------------------------


class TestResolveRORQuery:
    """IdentifierResolver: ROR query endpoint with fuzzy matching."""

    def test_query_fuzzy_match_returns_result(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(
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
        resolver, ror, _, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[MOCK_ROR_QUERY_ORG],
            isni_results=[],
        )
        result = resolver.resolve("Completely Different Organization Name")
        assert result is None


# --------------------------------------------------------------------------


class TestCountryHint:
    """IdentifierResolver: the optional country hint reaches ROR ?query= only."""

    def test_country_disambiguates_tied_ror_query_candidates(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[MOCK_ROR_QUERY_ORG_AR, MOCK_ROR_QUERY_ORG_CL],
            isni_results=[],
        )
        result = resolver.resolve("Universidad de Chile", country="CL")
        assert result is not None
        assert result.ror_id == "https://ror.org/bbbb2222"
        assert result.status == "auto"

    def test_no_country_hint_leaves_tie_ambiguous(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[MOCK_ROR_QUERY_ORG_AR, MOCK_ROR_QUERY_ORG_CL],
            isni_results=[],
        )
        result = resolver.resolve("Universidad de Chile")
        assert result is not None
        assert result.status == "review"

    def test_country_does_not_change_isni_call(self, tmp_path: Path) -> None:
        """ISNI SRU results carry no country field — the hint must not
        reach or affect the ISNI call at all."""
        resolver, _, isni, _ = _make_resolver(
            tmp_path, ror_org=None, ror_query_results=[], isni_results=[MOCK_ISNI_RESULT]
        )
        resolver.resolve("Ministerio de Hacienda", country="CL")
        isni.search_organizations.assert_called_once_with("Ministerio de Hacienda", max_records=5)

    def test_cache_key_isolated_by_country(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG, isni_results=[])
        resolver.resolve("Ministerio de Hacienda", country="CL")
        assert ror.search_affiliation.call_count == 1
        resolver.resolve("Ministerio de Hacienda", country="AR")
        assert ror.search_affiliation.call_count == 2, (
            "a different country must not reuse another country's cached result"
        )
        resolver.resolve("Ministerio de Hacienda", country="CL")
        assert ror.search_affiliation.call_count == 2, "same country should still hit cache"

    def test_no_country_and_explicit_none_share_a_cache_entry(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        resolver.resolve("Ministerio de Hacienda")
        resolver.resolve("Ministerio de Hacienda", country=None)
        assert ror.search_affiliation.call_count == 1


# --------------------------------------------------------------------------


class TestMergeBothSources:
    """IdentifierResolver: ROR and ISNI are both always checked and merged."""

    def test_isni_always_checked_even_when_ror_affiliation_succeeds(self, tmp_path: Path) -> None:
        resolver, ror, isni, _ = _make_resolver(
            tmp_path, ror_org=MOCK_ROR_ORG, isni_results=[MOCK_ISNI_RESULT]
        )
        resolver.resolve("Ministerio de Hacienda")
        assert isni.search_organizations.called, (
            "ISNI must be checked even when ROR affiliation already found a match"
        )

    def test_rors_own_linked_isni_wins_over_independent_isni_hit(self, tmp_path: Path) -> None:
        """ROR's own external_ids ISNI is verified registry data — prefer it
        over a separately fuzzy-matched ISNI SRU result for the same org."""
        resolver, _, _, _ = _make_resolver(
            tmp_path, ror_org=MOCK_ROR_ORG, isni_results=[MOCK_ISNI_RESULT]
        )
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.ror_id == "https://ror.org/01h6h5x94"
        assert result.isni_id == "0000000123456789"  # ROR's own, not MOCK_ISNI_RESULT's
        assert result.matched_via == "ror_affiliation+isni_sru"

    def test_independent_isni_used_when_ror_record_has_none(self, tmp_path: Path) -> None:
        ror_org_no_isni = {**MOCK_ROR_ORG, "external_ids": []}
        resolver, _, _, _ = _make_resolver(
            tmp_path, ror_org=ror_org_no_isni, isni_results=[MOCK_ISNI_RESULT]
        )
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.ror_id == "https://ror.org/01h6h5x94"
        assert result.isni_id == "000000040628717X"  # from the independent ISNI SRU hit

    def test_only_ror_found_returns_ror_match_unchanged(self, tmp_path: Path) -> None:
        ror_org_no_isni = {**MOCK_ROR_ORG, "external_ids": []}
        resolver, _, _, _ = _make_resolver(tmp_path, ror_org=ror_org_no_isni, isni_results=[])
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.matched_via == "ror_affiliation"
        assert result.isni_id is None

    def test_only_isni_found_returns_isni_match_unchanged(self, tmp_path: Path) -> None:
        resolver, _, _, _ = _make_resolver(
            tmp_path, ror_org=None, ror_query_results=[], isni_results=[MOCK_ISNI_RESULT]
        )
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.matched_via == "isni_sru"
        assert result.ror_id is None

    def test_review_status_propagates_through_merge(self, tmp_path: Path) -> None:
        """ROR query returns 2 identical-scoring candidates (ambiguous, status
        'review'). Even though ISNI independently finds a clean 'auto' match,
        the merged result must stay 'review' — ambiguity on either side wins."""
        ambiguous_org_a = {**MOCK_ROR_QUERY_ORG, "id": "https://ror.org/01q2pz218"}
        ambiguous_org_b = {**MOCK_ROR_QUERY_ORG, "id": "https://ror.org/99999999x"}
        clean_isni_hit = {**MOCK_ISNI_RESULT, "name": "Universidad de Chile"}
        resolver, _, _, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[ambiguous_org_a, ambiguous_org_b],
            isni_results=[clean_isni_hit],
        )
        result = resolver.resolve("Universidad de Chile")
        assert result is not None
        assert result.status == "review"


# --------------------------------------------------------------------------


class TestResolvePerson:
    """IdentifierResolver.resolve_person — ORCID resolution."""

    def test_unambiguous_hit_returns_auto_status(self, tmp_path: Path) -> None:
        resolver, _, _, orcid = _make_resolver(
            tmp_path, orcid_result={"num_found": 1, "orcids": ["0000-0002-1825-0097"]}
        )
        result = resolver.resolve_person("Jane", "Roe")
        assert result is not None
        assert result.orcid_id == "0000-0002-1825-0097"
        assert result.status == "auto"
        assert result.matched_via == "orcid_search"

    def test_ambiguous_hit_returns_review_status(self, tmp_path: Path) -> None:
        resolver, _, _, orcid = _make_resolver(
            tmp_path,
            orcid_result={"num_found": 3, "orcids": ["0000-0001-1111-1111", "0000-0002-2222-2222"]},
        )
        result = resolver.resolve_person("Juan", "Perez")
        assert result is not None
        assert result.status == "review"
        assert result.orcid_id == "0000-0001-1111-1111"  # top candidate, still surfaced

    def test_no_hits_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _, _ = _make_resolver(tmp_path, orcid_result={"num_found": 0, "orcids": []})
        assert resolver.resolve_person("Nobody", "Real") is None

    def test_passes_affiliation_through(self, tmp_path: Path) -> None:
        resolver, _, _, orcid = _make_resolver(tmp_path)
        resolver.resolve_person("Jane", "Roe", affiliation="Universidad de Chile")
        orcid.search_person.assert_called_once_with("Jane", "Roe", "Universidad de Chile")

    def test_empty_given_name_returns_none_without_network_call(self, tmp_path: Path) -> None:
        resolver, _, _, orcid = _make_resolver(tmp_path)
        assert resolver.resolve_person("", "Roe") is None
        assert not orcid.search_person.called

    def test_orcid_exception_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _, _ = _make_resolver(tmp_path, orcid_side_effect=RuntimeError("orcid down"))
        assert resolver.resolve_person("Jane", "Roe") is None

    def test_result_is_cached(self, tmp_path: Path) -> None:
        resolver, _, _, orcid = _make_resolver(
            tmp_path, orcid_result={"num_found": 1, "orcids": ["0000-0002-1825-0097"]}
        )
        resolver.resolve_person("Jane", "Roe")
        resolver.resolve_person("Jane", "Roe")
        assert orcid.search_person.call_count == 1

    def test_different_affiliation_not_cached_together(self, tmp_path: Path) -> None:
        resolver, _, _, orcid = _make_resolver(
            tmp_path, orcid_result={"num_found": 1, "orcids": ["0000-0002-1825-0097"]}
        )
        resolver.resolve_person("Jane", "Roe", affiliation="Org A")
        resolver.resolve_person("Jane", "Roe", affiliation="Org B")
        assert orcid.search_person.call_count == 2


# --------------------------------------------------------------------------


class TestResolveISNI:
    """IdentifierResolver: ISNI SRU fallback with fuzzy matching."""

    def test_isni_match_returns_result(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(
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
        resolver, _, _, _ = _make_resolver(tmp_path, ror_org=None, isni_results=[])
        result = resolver.resolve("Nonexistent Organization")
        assert result is None


# --------------------------------------------------------------------------


class TestCaching:
    """IdentifierResolver: disk cache behavior."""

    def test_cache_hit_avoids_network(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        resolver.resolve("Ministerio de Hacienda")
        assert ror.search_affiliation.call_count == 1
        resolver.resolve("Ministerio de Hacienda")
        assert ror.search_affiliation.call_count == 1

    def test_negative_result_cached(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=None, isni_results=[])
        resolver.resolve("Unknown Org Name")
        first_calls = ror.search_affiliation.call_count
        resolver.resolve("Unknown Org Name")
        assert ror.search_affiliation.call_count == first_calls

    def test_different_names_not_cached_together(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        resolver.resolve("Ministerio de Hacienda")
        resolver.resolve("Universidad de Chile")
        assert ror.search_affiliation.call_count == 2


# --------------------------------------------------------------------------


class TestErrorHandling:
    """IdentifierResolver: graceful error handling."""

    def test_ror_affiliation_exception_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _, _ = _make_resolver(
            tmp_path,
            ror_affil_side_effect=RuntimeError("network error"),
            ror_query_results=[],
            isni_results=[],
        )
        result = resolver.resolve("Test Org")
        assert result is None

    def test_ror_query_exception_falls_through_to_isni(self, tmp_path: Path) -> None:
        resolver, _, isni, _ = _make_resolver(
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
        resolver, _, _, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[],
            isni_side_effect=RuntimeError("isni error"),
        )
        result = resolver.resolve("Test Org")
        assert result is None

    def test_all_fail_returns_none(self, tmp_path: Path) -> None:
        resolver, _, _, _ = _make_resolver(
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
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
        assert resolver.resolve("") is None
        assert not ror.search_affiliation.called

    def test_whitespace_name_returns_none(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG)
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
