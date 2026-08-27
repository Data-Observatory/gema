"""Live tests for identifier resolution against real ROR/ISNI/ORCID APIs.

ROR and ISNI need no credentials (public registries). ORCID needs free
``ORCID_CLIENT_ID``/``ORCID_CLIENT_SECRET`` (self-service registration,
https://orcid.org/developer-tools) — loaded from ``.env`` if present;
ORCID-dependent tests skip (not fail) when those aren't set, since the
client itself disables gracefully rather than erroring without them.

Run manually with `-m live` or `make live-identifier-check` (see CLAUDE.md's
"Live tests stay manual-only" rule) — periodically, and before any dev->main
PR touching identifier resolution (ROR client, fuzzy matching, abbreviation
dict, country-hint logic).

Assertions favor invariants (a well-known org resolves unambiguously; an
ambiguous name never auto-attaches) over exact registry content, so the
suite doesn't flake when ROR/ISNI/ORCID add or edit entries over time.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import find_dotenv, load_dotenv

from metadata_enricher.enrichers.identifier_resolver import IdentifierResolver

load_dotenv(find_dotenv(usecwd=True))

pytestmark = pytest.mark.live

_HAS_ORCID_CREDS = bool(os.environ.get("ORCID_CLIENT_ID") and os.environ.get("ORCID_CLIENT_SECRET"))
_ORCID_SKIP_REASON = "Set ORCID_CLIENT_ID/ORCID_CLIENT_SECRET to run ORCID live tests"


@pytest.fixture
def resolver(tmp_path: Path) -> IdentifierResolver:
    # Fresh cache dir per test — real network hit every run, not a stale
    # cached answer from a previous run's registry state or code version.
    return IdentifierResolver(cache_dir=tmp_path / "identifiers")


class TestWellKnownOrgsResolveUnambiguously:
    """Large, unambiguous institutions should always auto-resolve (ROR/ISNI
    only — no credentials needed)."""

    def test_universidad_de_chile(self, resolver: IdentifierResolver) -> None:
        match = resolver.resolve("Universidad de Chile", country="CL")
        assert match is not None
        assert match.status == "auto"
        assert match.ror_id == "https://ror.org/047gc3g35"

    def test_pontificia_universidad_catolica_de_chile(
        self, resolver: IdentifierResolver
    ) -> None:
        match = resolver.resolve("Pontificia Universidad Católica de Chile", country="CL")
        assert match is not None
        assert match.status == "auto"
        assert match.ror_id == "https://ror.org/04teye511"


class TestAbbreviationExpansionResolvesLive:
    """Spanish abbreviation dict (fuzzy_matcher._ABBREVIATIONS) against real ROR/ISNI."""

    def test_ministerio_de_salud_isni(self, resolver: IdentifierResolver) -> None:
        match = resolver.resolve("Ministerio de Salud", country="CL")
        assert match is not None
        assert match.isni_id is not None


class TestAmbiguousOrgNamesNeverAutoAttach:
    """A wrong PID is worse than a missing one — ambiguity must never resolve
    to status=="auto", even if the registries return *some* candidate."""

    def test_generic_university_abbreviation(self, resolver: IdentifierResolver) -> None:
        match = resolver.resolve("Univ. Católica", country="CL")
        if match is not None:
            assert match.status != "auto"


@pytest.mark.skipif(not _HAS_ORCID_CREDS, reason=_ORCID_SKIP_REASON)
class TestAmbiguousPersonNamesNeverAutoAttach:
    """Common Spanish names with no affiliation hint genuinely return
    multiple ORCID hits — must land status=="review", never "auto"."""

    @pytest.mark.parametrize(
        ("given", "family"),
        [("Juan", "Pérez"), ("Maria", "González"), ("Carlos", "Rodríguez")],
    )
    def test_common_name_no_affiliation(
        self, resolver: IdentifierResolver, given: str, family: str
    ) -> None:
        match = resolver.resolve_person(given, family)
        assert match is not None, f"expected ORCID to find candidates for {given} {family}"
        assert match.status == "review"
