"""Tests for enrichers.identifier_types."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from metadata_enricher.enrichers.identifier_types import IdentifierMatch


# ---------- Construction ----------


class TestIdentifierMatchConstruction:
    """IdentifierMatch: construction and defaults."""

    def test_default_construction(self) -> None:
        match = IdentifierMatch()
        assert match.ror_id is None
        assert match.isni_id is None
        assert match.org_name == ""
        assert match.confidence == 0.0
        assert match.matched_via == ""
        assert match.parent_ror_id is None
        assert match.parent_name is None
        assert match.status == "nomatch"

    def test_full_construction(self) -> None:
        match = IdentifierMatch(
            ror_id="https://ror.org/01qe7f394",
            isni_id="000000040628717X",
            org_name="Ministerio de Salud de Chile",
            confidence=0.95,
            matched_via="ror_affiliation",
            parent_ror_id="https://ror.org/02sevrz47",
            parent_name="Gobierno de Chile",
            status="auto",
        )
        assert match.ror_id == "https://ror.org/01qe7f394"
        assert match.isni_id == "000000040628717X"
        assert match.org_name == "Ministerio de Salud de Chile"
        assert match.confidence == 0.95
        assert match.matched_via == "ror_affiliation"
        assert match.parent_ror_id == "https://ror.org/02sevrz47"
        assert match.parent_name == "Gobierno de Chile"
        assert match.status == "auto"

    def test_partial_construction_ror_only(self) -> None:
        match = IdentifierMatch(
            ror_id="https://ror.org/01q2pz218",
            org_name="Universidad de Chile",
            confidence=0.92,
            matched_via="ror_query_fuzzy",
            status="auto",
        )
        assert match.ror_id == "https://ror.org/01q2pz218"
        assert match.isni_id is None
        assert match.parent_ror_id is None

    def test_partial_construction_isni_only(self) -> None:
        match = IdentifierMatch(
            isni_id="000000040628717X",
            org_name="Some Organization",
            confidence=0.88,
            matched_via="isni_sru",
            status="review",
        )
        assert match.isni_id == "000000040628717X"
        assert match.ror_id is None
        assert match.status == "review"


# ---------- Validation ----------


class TestIdentifierMatchValidation:
    """IdentifierMatch: pydantic validation."""

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            IdentifierMatch(unknown_field="bad")  # type: ignore[call-arg]

    def test_confidence_accepts_zero(self) -> None:
        match = IdentifierMatch(confidence=0.0)
        assert match.confidence == 0.0

    def test_confidence_accepts_one(self) -> None:
        match = IdentifierMatch(confidence=1.0)
        assert match.confidence == 1.0

    def test_org_name_accepts_empty_string(self) -> None:
        match = IdentifierMatch(org_name="")
        assert match.org_name == ""

    def test_status_accepts_valid_values(self) -> None:
        for status in ("auto", "review", "nomatch"):
            match = IdentifierMatch(status=status)
            assert match.status == status

    def test_matched_via_accepts_valid_values(self) -> None:
        for via in ("ror_affiliation", "ror_query_fuzzy", "isni_sru"):
            match = IdentifierMatch(matched_via=via)
            assert match.matched_via == via


# ---------- Serialization ----------


class TestIdentifierMatchSerialization:
    """IdentifierMatch: model_dump and model_validate round-trip."""

    def test_round_trip(self) -> None:
        original = IdentifierMatch(
            ror_id="https://ror.org/01qe7f394",
            isni_id="000000040628717X",
            org_name="Test Org",
            confidence=0.95,
            matched_via="ror_affiliation",
            parent_ror_id="https://ror.org/02sevrz47",
            parent_name="Parent Org",
            status="auto",
        )
        dumped = original.model_dump()
        restored = IdentifierMatch.model_validate(dumped)
        assert restored == original

    def test_model_dump_for_cache_storage(self) -> None:
        """IdentifierMatch must serialize to a plain dict for diskcache storage."""
        match = IdentifierMatch(
            ror_id="https://ror.org/01qe7f394",
            org_name="Test",
            status="auto",
        )
        dumped = match.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["ror_id"] == "https://ror.org/01qe7f394"
        assert dumped["isni_id"] is None
