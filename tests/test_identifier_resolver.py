"""Tests for enrichers.identifier_resolver."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from metadata_enricher.enrichers.identifier_overrides import IdentifierOverrides
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

MOCK_ROR_ORG_ES = {
    # Real record shape (verified against https://api.ror.org/organizations/04q93ds34
    # directly, not assumed): "Instituto de Políticas y Bienes Públicos", a
    # research facility in Madrid, Spain -- the actual wrong-country match
    # ROR's own ?affiliation= endpoint returned for a Chilean input in a real
    # golden fixture (docs/cdif_pivot_implementation_plan.md's Post-PR#45
    # investigation, Open Question O-5).
    "id": "https://ror.org/04q93ds34",
    "names": [
        {"lang": "es", "types": ["ror_display", "label"], "value": "Instituto de Políticas y Bienes Públicos"},
    ],
    "external_ids": [],
    "relationships": [],
    "locations": [{"geonames_details": {"country_code": "ES"}}],
}

MOCK_ROR_ORG_CL = {
    **MOCK_ROR_ORG,
    "locations": [{"geonames_details": {"country_code": "CL"}}],
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
    overrides: IdentifierOverrides | None = None,
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
        overrides=overrides,
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


class TestRORAffiliationCountryMismatch:
    """IdentifierResolver: a real, verified bug (Open Question O-5) — ROR's
    own ?affiliation= endpoint can confidently pick a wrong-country
    organization when names share a distinctive word. Its "chosen" pick is
    still trusted over its own score field (never re-ranked, never
    overridden) — a known country mismatch only demotes the match to
    status="review", which identifier_enricher.py's existing status=="auto"
    gate already refuses to auto-attach (no changes needed there)."""

    def test_country_mismatch_demotes_to_review(self, tmp_path: Path) -> None:
        resolver, _, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG_ES, isni_results=[])
        result = resolver.resolve("Oficina de Estudios y Políticas Agrarias", country="CL")
        assert result is not None
        assert result.status == "review"
        assert result.confidence == 0.5
        # ROR's own pick is still surfaced (for logging/review), just not
        # trusted enough to auto-attach -- never silently substituted.
        assert result.ror_id == "https://ror.org/04q93ds34"

    def test_country_match_stays_auto(self, tmp_path: Path) -> None:
        resolver, _, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG_CL, isni_results=[])
        result = resolver.resolve("Ministerio de Hacienda", country="CL")
        assert result is not None
        assert result.status == "auto"
        assert result.confidence == 1.0

    def test_no_country_hint_stays_auto(self, tmp_path: Path) -> None:
        """No hint at all -- nothing to compare against, ROR's chosen pick
        is trusted as before this fix existed."""
        resolver, _, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG_ES, isni_results=[])
        result = resolver.resolve("Oficina de Estudios y Políticas Agrarias")
        assert result is not None
        assert result.status == "auto"
        assert result.confidence == 1.0

    def test_org_with_no_known_country_not_penalized(self, tmp_path: Path) -> None:
        """MOCK_ROR_ORG carries no locations/country at all -- unknown is
        not a mismatch, same philosophy fuzzy_matcher.match_organization's
        country_hint already uses for the ?query= path."""
        resolver, _, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG, isni_results=[])
        result = resolver.resolve("Ministerio de Hacienda", country="CL")
        assert result is not None
        assert result.status == "auto"
        assert result.confidence == 1.0

    def test_demoted_affiliation_match_falls_through_to_ror_query(self, tmp_path: Path) -> None:
        """Regression: a country-demoted ?affiliation= match must not
        silently win by default -- ?query= (which DOES apply country as a
        fuzzy-match deprioritizer) gets a real chance to find the correct
        org instead. Here it does: the wrong-country Madrid pick is
        replaced by a correctly-scored Chilean ?query= candidate for the
        same real organization (ODEPA)."""
        mock_odepa_query_org = {
            "id": "https://ror.org/bbbb2222",
            "names": [
                {
                    "lang": "es",
                    "types": ["ror_display"],
                    "value": "Oficina de Estudios y Políticas Agrarias",
                }
            ],
            "external_ids": [],
            "relationships": [],
            "locations": [{"geonames_details": {"country_code": "CL"}}],
        }
        resolver, _, _, _ = _make_resolver(
            tmp_path,
            ror_org=MOCK_ROR_ORG_ES,
            ror_query_results=[mock_odepa_query_org],
            isni_results=[],
        )
        result = resolver.resolve("Oficina de Estudios y Políticas Agrarias", country="CL")
        assert result is not None
        assert result.ror_id == "https://ror.org/bbbb2222"
        assert result.status == "auto"
        assert result.matched_via == "ror_query_fuzzy"

    def test_demoted_affiliation_match_kept_when_query_finds_nothing_better(
        self, tmp_path: Path
    ) -> None:
        """When ?query= also comes back empty/no-better, the demoted
        ?affiliation= match is still surfaced (status="review", never
        silently dropped) rather than losing the match entirely --
        matches the pre-fix behavior for this specific sub-case."""
        resolver, _, _, _ = _make_resolver(
            tmp_path, ror_org=MOCK_ROR_ORG_ES, ror_query_results=[], isni_results=[]
        )
        result = resolver.resolve("Oficina de Estudios y Políticas Agrarias", country="CL")
        assert result is not None
        assert result.status == "review"
        assert result.ror_id == "https://ror.org/04q93ds34"


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
    """IdentifierResolver: the optional country hint reaches ROR ?query=
    (disambiguates/deprioritizes during scoring) and ROR ?affiliation=
    (post-hoc sanity check on ROR's own "chosen" pick — see
    TestRORAffiliationCountryMismatch below for that path specifically)."""

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


class TestOverridesPrecedence:
    """IdentifierResolver: a human-curated override wins outright."""

    def _overrides_from(self, tmp_path: Path, yaml_content: str) -> IdentifierOverrides:
        path = tmp_path / "overrides.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        return IdentifierOverrides(path)

    def test_override_hit_skips_network_entirely(self, tmp_path: Path) -> None:
        overrides = self._overrides_from(
            tmp_path, "overrides:\n  - name: Ministerio de Hacienda\n    ror_id: https://ror.org/curated\n"
        )
        resolver, ror, isni, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG, overrides=overrides)
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.ror_id == "https://ror.org/curated"
        assert result.matched_via == "override"
        assert not ror.search_affiliation.called
        assert not ror.search_query.called
        assert not isni.search_organizations.called

    def test_override_miss_falls_through_to_normal_resolution(self, tmp_path: Path) -> None:
        overrides = self._overrides_from(
            tmp_path, "overrides:\n  - name: Some Unrelated Org\n    ror_id: https://ror.org/other\n"
        )
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG, overrides=overrides)
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.ror_id == "https://ror.org/01h6h5x94"
        assert result.matched_via == "ror_affiliation"
        assert ror.search_affiliation.called

    def test_no_overrides_configured_behaves_as_before(self, tmp_path: Path) -> None:
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG, overrides=None)
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.matched_via == "ror_affiliation"

    def test_override_result_is_not_cached(self, tmp_path: Path) -> None:
        """Overrides are already free -- no need to round-trip through the
        disk cache, and doing so would need its own cache-key scheme."""
        overrides = self._overrides_from(
            tmp_path, "overrides:\n  - name: Ministerio de Hacienda\n    ror_id: https://ror.org/curated\n"
        )
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG, overrides=overrides)
        resolver.resolve("Ministerio de Hacienda")
        resolver.resolve("Ministerio de Hacienda")
        assert not ror.search_affiliation.called

    def test_country_specific_override_takes_precedence(self, tmp_path: Path) -> None:
        overrides = self._overrides_from(
            tmp_path,
            "overrides:\n"
            "  - name: Ministerio de Hacienda\n"
            "    country: CL\n"
            "    ror_id: https://ror.org/cl-specific\n",
        )
        resolver, ror, _, _ = _make_resolver(tmp_path, ror_org=MOCK_ROR_ORG, overrides=overrides)
        result = resolver.resolve("Ministerio de Hacienda", country="CL")
        assert result is not None
        assert result.ror_id == "https://ror.org/cl-specific"
        assert not ror.search_affiliation.called


# --------------------------------------------------------------------------


class TestMergeBothSources:
    """IdentifierResolver: ISNI is checked only when ROR's own record has none."""

    def test_isni_skipped_when_ror_already_has_its_own_isni(self, tmp_path: Path) -> None:
        """A ROR record already carrying a linked ISNI is trusted outright —
        no independent ISNI SRU call at all, since that call could only ever
        demote (never confirm) a match that's already verified registry data."""
        resolver, ror, isni, _ = _make_resolver(
            tmp_path, ror_org=MOCK_ROR_ORG, isni_results=[MOCK_ISNI_RESULT]
        )
        resolver.resolve("Ministerio de Hacienda")
        assert not isni.search_organizations.called

    def test_rors_own_linked_isni_returned_as_is(self, tmp_path: Path) -> None:
        """ROR's own external_ids ISNI is verified registry data — used
        as-is, with no independent ISNI SRU lookup to disagree with it."""
        resolver, _, _, _ = _make_resolver(
            tmp_path, ror_org=MOCK_ROR_ORG, isni_results=[MOCK_ISNI_RESULT]
        )
        result = resolver.resolve("Ministerio de Hacienda")
        assert result is not None
        assert result.ror_id == "https://ror.org/01h6h5x94"
        assert result.isni_id == "0000000123456789"  # ROR's own, not MOCK_ISNI_RESULT's
        assert result.matched_via == "ror_affiliation"
        assert result.status == "auto"
        assert result.confidence == 1.0

    def test_isni_skipped_on_ror_query_fuzzy_match_too(self, tmp_path: Path) -> None:
        """Same skip behavior on the ?query=+fuzzy path, not just ?affiliation=."""
        org_with_isni = {
            **MOCK_ROR_QUERY_ORG,
            "external_ids": [
                {"type": "isni", "preferred": "0000 0009 9999 9999", "all": []},
            ],
        }
        resolver, _, isni, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[org_with_isni],
            isni_results=[MOCK_ISNI_RESULT],
        )
        result = resolver.resolve("Universidad de Chile")
        assert result is not None
        assert result.isni_id == "0000000999999999"
        assert result.matched_via == "ror_query_fuzzy"
        assert not isni.search_organizations.called

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

    def test_ambiguous_ror_match_with_own_isni_still_checks_isni_independently(
        self, tmp_path: Path
    ) -> None:
        """The isni-skip optimization only applies when the ROR match is
        itself unambiguous ('auto') -- an ambiguous ('review') ROR match
        stays 'review' either way, so there's no reason to skip the one
        extra corroborating check. ROR's own linked ISNI must still win the
        merge (never silently replaced by the independently-fuzzy-matched
        one) -- see _merge_org_matches's defensive `or` preference."""
        ambiguous_org_a = {
            **MOCK_ROR_QUERY_ORG,
            "id": "https://ror.org/01q2pz218",
            "external_ids": [
                {"type": "isni", "preferred": "0000 0001 1111 1111", "all": []},
            ],
        }
        ambiguous_org_b = {**MOCK_ROR_QUERY_ORG, "id": "https://ror.org/99999999x"}
        resolver, _, isni, _ = _make_resolver(
            tmp_path,
            ror_org=None,
            ror_query_results=[ambiguous_org_a, ambiguous_org_b],
            isni_results=[MOCK_ISNI_RESULT],
        )
        result = resolver.resolve("Universidad de Chile")
        assert isni.search_organizations.called, (
            "an ambiguous ROR match must not skip the independent ISNI check"
        )
        assert result is not None
        assert result.status == "review"
        assert result.isni_id == "0000000111111111"  # ROR's own -- not MOCK_ISNI_RESULT's


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
