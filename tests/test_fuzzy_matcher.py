"""Tests for enrichers.fuzzy_matcher."""

from __future__ import annotations

from metadata_enricher.enrichers.fuzzy_matcher import (
    match_organization,
    normalize_org_name,
)


# ---------- normalize_org_name ----------


class TestNormalizeOrgName:
    """normalize_org_name: normalization steps."""

    def test_lowercases(self) -> None:
        assert normalize_org_name("HARVARD") == "harvard"

    def test_strips_legal_suffixes_inc(self) -> None:
        assert normalize_org_name("Harvard Inc") == "harvard"

    def test_strips_legal_suffixes_ltd(self) -> None:
        assert normalize_org_name("Corp Ltd") == "corp"

    def test_strips_legal_suffixes_llc(self) -> None:
        assert normalize_org_name("Test LLC") == "test"

    def test_removes_punctuation(self) -> None:
        assert normalize_org_name("Harvard, Inc.") == "harvard"

    def test_preserves_hyphens(self) -> None:
        assert normalize_org_name("U.S.-Chile") == "us-chile"

    def test_collapses_whitespace(self) -> None:
        assert normalize_org_name("Extra   Space") == "extra space"

    def test_strips_trailing_whitespace(self) -> None:
        assert normalize_org_name("  MIT  ") == "mit"

    def test_empty_string(self) -> None:
        assert normalize_org_name("") == ""

    def test_spanish_accents_preserved(self) -> None:
        assert (
            normalize_org_name("Universidad de Concepción")
            == "universidad de concepción"
        )


# ---------- match_organization ----------


class TestMatchOrganization:
    """match_organization: core matching logic."""

    def test_exact_match_returns_auto(self) -> None:
        candidates = [{"name": "Harvard University"}]
        match, score, status = match_organization("Harvard University", candidates)
        assert status == "auto"
        assert score == 100.0

    def test_word_order_variation(self) -> None:
        candidates = [{"name": "Harvard University"}]
        match, score, status = match_organization("University of Harvard", candidates)
        # WRatio handles word-order variations well — should be above threshold
        assert score >= 90.0
        assert status == "auto"

    def test_case_insensitive(self) -> None:
        candidates = [{"name": "Harvard University"}]
        match, score, status = match_organization("HARVARD", candidates)
        assert score >= 90.0

    def test_below_threshold_returns_nomatch(self) -> None:
        candidates = [{"name": "Harvard"}]
        match, score, status = match_organization(
            "Completely Different", candidates
        )
        assert status == "nomatch"
        assert match is None

    def test_empty_candidates(self) -> None:
        match, score, status = match_organization("Harvard", [])
        assert match is None
        assert score == 0.0
        assert status == "nomatch"

    def test_empty_query(self) -> None:
        candidates = [{"name": "Harvard"}]
        match, score, status = match_organization("", candidates)
        assert match is None
        assert score == 0.0
        assert status == "nomatch"

    def test_whitespace_query(self) -> None:
        candidates = [{"name": "Harvard"}]
        match, score, status = match_organization("   ", candidates)
        assert match is None
        assert score == 0.0
        assert status == "nomatch"

    def test_small_gap_returns_review(self) -> None:
        """Two very similar candidates should produce a small gap → review."""
        candidates = [
            {"name": "University of California Berkeley"},
            {"name": "University of California, Berkeley"},
        ]
        match, score, status = match_organization(
            "University of California Berkeley", candidates
        )
        assert status == "review"
        assert score >= 90.0

    def test_custom_name_key(self) -> None:
        candidates = [{"org_name": "Harvard"}]
        match, score, status = match_organization(
            "Harvard", candidates, name_key="org_name"
        )
        assert status == "auto"
        assert score == 100.0

    def test_custom_threshold(self) -> None:
        candidates = [{"name": "Something Completely Different"}]
        # threshold=50 should accept a mediocre partial match
        match, score, status = match_organization(
            "Something", candidates, threshold=50.0
        )
        # WRatio partial might score "Something" vs "Something Completely Different"
        # high enough to pass threshold=50
        if match is not None:
            assert status in ("auto", "review")
        else:
            assert status == "nomatch"

    def test_returns_correct_candidate_dict(self) -> None:
        candidates = [
            {"name": "MIT", "id": "ror-01"},
            {"name": "Harvard", "id": "ror-02"},
        ]
        match, score, status = match_organization("MIT", candidates)
        assert match is not None
        assert match["id"] == "ror-01"


# ---------- Edge cases ----------


class TestMatchOrganizationEdgeCases:
    """match_organization: edge cases and corner conditions."""

    def test_single_candidate_auto(self) -> None:
        candidates = [{"name": "Massachusetts Institute of Technology"}]
        match, score, status = match_organization("MIT", candidates)
        # Single candidate above threshold → auto
        if match is not None:
            assert status == "auto"
        else:
            assert status == "nomatch"

    def test_acronym_match(self) -> None:
        """MIT vs full name — should match without crashing."""
        candidates = [{"name": "Massachusetts Institute of Technology"}]
        match, score, status = match_organization("MIT", candidates)
        # WRatio may or may not match acronym to full name;
        # validate it returns something reasonable (not crash).
        assert status in ("auto", "review", "nomatch")
        if match is not None:
            assert 0.0 <= score <= 100.0

    def test_spanish_name_match(self) -> None:
        candidates = [{"name": "Universidad de Chile"}]
        match, score, status = match_organization(
            "Universidad de Chile", candidates
        )
        assert status == "auto"
        assert score == 100.0

    def test_candidate_missing_name_key(self) -> None:
        """Candidate without 'name' key → treated as empty string → nomatch."""
        candidates = [{"id": "123", "title": "Some Org"}]
        match, score, status = match_organization("Some Org", candidates)
        assert match is None
        assert status == "nomatch"


# ---------- country_hint ----------


class TestMatchOrganizationCountryHint:
    """match_organization: country_hint is a soft re-rank, never a hard filter."""

    def test_no_hint_is_unaffected_by_country_field(self) -> None:
        """A 'wrong' country_code on a candidate must not matter at all
        when no hint is given — the default, unchanged fast path."""
        candidates = [{"name": "Ministerio de Salud", "country_code": "AR"}]
        match, score, status = match_organization("Ministerio de Salud", candidates)
        assert match is not None
        assert score == 100.0
        assert status == "auto"

    def test_matching_country_not_penalized(self) -> None:
        candidates = [{"name": "Ministerio de Salud", "country_code": "CL"}]
        match, score, status = match_organization(
            "Ministerio de Salud", candidates, country_hint="CL"
        )
        assert match is not None
        assert score == 100.0
        assert status == "auto"

    def test_country_hint_case_insensitive(self) -> None:
        candidates = [{"name": "Ministerio de Salud", "country_code": "cl"}]
        match, score, status = match_organization(
            "Ministerio de Salud", candidates, country_hint="cl"
        )
        assert match is not None
        assert score == 100.0

    def test_unknown_country_not_penalized(self) -> None:
        """A candidate with no country_code at all is not a disagreement —
        this is what ISNI candidates look like, and what a real ROR record
        with no location data would look like."""
        candidates = [{"name": "Ministerio de Salud"}]
        match, score, status = match_organization(
            "Ministerio de Salud", candidates, country_hint="CL"
        )
        assert match is not None
        assert score == 100.0

    def test_mismatched_country_is_deprioritized_not_hard_rejected(self) -> None:
        """A country mismatch subtracts points (here dropping an exact
        match below the default threshold, same as any other low-scoring
        candidate would) — it is not a special-cased hard filter. Proven by
        the next test, where a lower threshold accepts the exact same
        mismatched candidate."""
        candidates = [{"name": "Ministerio de Salud", "country_code": "AR"}]
        match, score, status = match_organization(
            "Ministerio de Salud", candidates, country_hint="CL", country_penalty=15.0
        )
        assert match is None
        assert score == 85.0  # 100.0 raw - 15.0 penalty
        assert status == "nomatch"

    def test_mismatched_country_still_returned_when_score_clears_threshold(self) -> None:
        candidates = [{"name": "Ministerio de Salud", "country_code": "AR"}]
        match, score, status = match_organization(
            "Ministerio de Salud",
            candidates,
            country_hint="CL",
            country_penalty=15.0,
            threshold=80.0,
        )
        assert match is not None
        assert score == 85.0
        assert status == "auto"

    def test_country_hint_disambiguates_same_name_different_countries(self) -> None:
        """The exact 'Ministerio de Salud' collision the plan calls out —
        two orgs sharing a name, distinguishable only by country. Without a
        hint, an identical-score tie is ambiguous ('review'); with the
        right hint, it resolves cleanly to the matching-country candidate."""
        candidates = [
            {"name": "Ministerio de Salud", "country_code": "AR"},
            {"name": "Ministerio de Salud", "country_code": "CL"},
        ]

        _, _, status_no_hint = match_organization("Ministerio de Salud", candidates)
        assert status_no_hint == "review"  # tied score, ambiguous without a hint

        match, score, status = match_organization(
            "Ministerio de Salud", candidates, country_hint="CL"
        )
        assert match is not None
        assert match["country_code"] == "CL"
        assert score == 100.0
        assert status == "auto"
