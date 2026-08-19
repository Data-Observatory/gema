"""Identifier resolver: ROR/ISNI fallback chain with disk caching."""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import diskcache

from metadata_enricher.enrichers.fuzzy_matcher import match_organization, normalize_org_name
from metadata_enricher.enrichers.identifier_types import IdentifierMatch
from metadata_enricher.enrichers.isni_client import ISNIClient
from metadata_enricher.enrichers.orcid_client import ORCIDClient
from metadata_enricher.enrichers.ror_client import (
    RORClient,
    extract_isni,
    extract_parent,
    get_display_name,
)

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "gema" / "identifiers"
DEFAULT_TTL = timedelta(days=30)


class IdentifierResolver:
    """Resolves organization and person names to ROR/ISNI/ORCID identifiers.

    Organization resolution (``resolve``) always checks BOTH registries —
    it does not stop at the first hit:
    1. Check disk cache (key = SHA-256 of normalized name).
    2. ROR ?affiliation= endpoint, then ?query= + rapidfuzz fuzzy matching
       (threshold 90) if affiliation found nothing.
    3. ISNI SRU pica.nw search + fuzzy matching — always attempted, even if
       ROR already found a match, since ROR and ISNI cover different
       organizations and either can independently confirm an identifier the
       other missed.
    4. If both ROR and ISNI found something, the two matches are merged into
       one ``IdentifierMatch`` carrying both identifiers. If only one source
       found something, that match is returned unchanged. If neither did,
       returns None (cached as a negative result).

    Person resolution (``resolve_person``) looks up ORCID by exact
    given-name/family-name (+ optional affiliation) — see its docstring for
    the ambiguity-handling policy.

    All API failures are caught and logged — the resolver never raises.
    Negative results are cached to avoid repeated API calls.
    """

    def __init__(
        self,
        ror_client: RORClient | None = None,
        isni_client: ISNIClient | None = None,
        orcid_client: ORCIDClient | None = None,
        cache_dir: Path | None = None,
        cache_ttl: timedelta = DEFAULT_TTL,
        fuzzy_threshold: float = 90.0,
    ) -> None:
        self._ror = ror_client or RORClient()
        self._isni = isni_client or ISNIClient()
        self._orcid = orcid_client or ORCIDClient()
        self._threshold = fuzzy_threshold

        cache_dir = cache_dir or DEFAULT_CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: diskcache.Cache = diskcache.Cache(str(cache_dir))
        self._cache_ttl = int(cache_ttl.total_seconds())

    def resolve(self, name: str) -> IdentifierMatch | None:
        if not name or not name.strip():
            return None

        normalized = normalize_org_name(name)
        if not normalized:
            return None

        cache_key = self._make_key("org", normalized)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if cached.get("__negative__"):
                return None
            return IdentifierMatch.model_validate(cached)

        result = self._try_resolve(name, normalized)
        self._store(cache_key, result)
        return result

    def resolve_person(
        self, given_names: str, family_name: str, affiliation: str | None = None
    ) -> IdentifierMatch | None:
        """Resolve a person to an ORCID iD by exact given/family name.

        Ambiguity policy: if the search returns more than one hit (even after
        narrowing with *affiliation*), the top candidate is still returned but
        with ``status="review"`` — callers should treat that as "found, but
        don't auto-attach without a human check" (a wrong ORCID on a person is
        worse than a missing one). Exactly one hit returns ``status="auto"``.
        """
        if not given_names.strip() or not family_name.strip():
            return None

        normalized = normalize_org_name(f"{given_names} {family_name}")
        if affiliation:
            normalized += f"|{normalize_org_name(affiliation)}"
        cache_key = self._make_key("person", normalized)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if cached.get("__negative__"):
                return None
            return IdentifierMatch.model_validate(cached)

        result = self._try_orcid(given_names, family_name, affiliation)
        self._store(cache_key, result)
        return result

    def close(self) -> None:
        self._cache.close()
        self._ror.close()
        self._isni.close()
        self._orcid.close()

    def __enter__(self) -> IdentifierResolver:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _store(self, cache_key: str, result: IdentifierMatch | None) -> None:
        if result is not None:
            self._cache.set(cache_key, result.model_dump(), expire=self._cache_ttl)
        else:
            self._cache.set(cache_key, {"__negative__": True}, expire=self._cache_ttl)

    def _make_key(self, kind: str, normalized_name: str) -> str:
        return hashlib.sha256(f"{kind}:{normalized_name}".encode()).hexdigest()

    def _try_resolve(self, original_name: str, normalized_name: str) -> IdentifierMatch | None:
        ror_match = self._try_ror_affiliation(original_name)
        if ror_match is None:
            ror_match = self._try_ror_query(original_name, normalized_name)

        isni_match = self._try_isni(original_name, normalized_name)

        if ror_match is None:
            return isni_match
        if isni_match is None:
            return ror_match
        return self._merge_org_matches(ror_match, isni_match)

    def _merge_org_matches(
        self, ror_match: IdentifierMatch, isni_match: IdentifierMatch
    ) -> IdentifierMatch:
        """Combine independent ROR and ISNI matches for the same org name.

        ROR's own linked ISNI (if it has one) is preferred over the
        independently fuzzy-matched ISNI SRU result, since it's verified
        registry data rather than a name-similarity guess.
        """
        return IdentifierMatch(
            ror_id=ror_match.ror_id,
            isni_id=ror_match.isni_id or isni_match.isni_id,
            org_name=ror_match.org_name,
            confidence=min(ror_match.confidence, isni_match.confidence),
            matched_via=f"{ror_match.matched_via}+{isni_match.matched_via}",
            parent_ror_id=ror_match.parent_ror_id,
            parent_name=ror_match.parent_name,
            status="review" if "review" in (ror_match.status, isni_match.status) else "auto",
        )

    def _try_ror_affiliation(self, name: str) -> IdentifierMatch | None:
        try:
            org = self._ror.search_affiliation(name)
        except Exception as exc:
            logger.warning("ROR affiliation search failed for %r: %s", name, exc)
            return None
        if org is None:
            return None
        return self._build_match_from_ror(org, "ror_affiliation")

    def _try_ror_query(self, name: str, normalized_name: str) -> IdentifierMatch | None:
        try:
            candidates_raw = self._ror.search_query(name, limit=5)
        except Exception as exc:
            logger.warning("ROR query search failed for %r: %s", name, exc)
            return None
        if not candidates_raw:
            return None
        candidates = [{"name": get_display_name(o), **o} for o in candidates_raw]
        best, score, status = match_organization(
            name, candidates, name_key="name", threshold=self._threshold
        )
        if best is None:
            return None
        return self._build_match_from_ror(best, "ror_query_fuzzy", score / 100.0, status)

    def _try_isni(self, name: str, normalized_name: str) -> IdentifierMatch | None:
        try:
            results = self._isni.search_organizations(name, max_records=5)
        except Exception as exc:
            logger.warning("ISNI search failed for %r: %s", name, exc)
            return None
        if not results:
            return None
        candidates = [{"name": r.get("name") or "", **r} for r in results]
        best, score, status = match_organization(
            name, candidates, name_key="name", threshold=self._threshold
        )
        if best is None:
            return None
        return IdentifierMatch(
            isni_id=best.get("isni"),
            org_name=best.get("name") or name,
            confidence=score / 100.0,
            matched_via="isni_sru",
            status=status,
        )

    def _try_orcid(
        self, given_names: str, family_name: str, affiliation: str | None
    ) -> IdentifierMatch | None:
        try:
            result = self._orcid.search_person(given_names, family_name, affiliation)
        except Exception as exc:
            logger.warning(
                "ORCID search failed for %r %r: %s", given_names, family_name, exc
            )
            return None
        orcids = result.get("orcids") or []
        if not orcids:
            return None
        status = "auto" if result.get("num_found") == 1 else "review"
        return IdentifierMatch(
            orcid_id=orcids[0],
            org_name=f"{given_names} {family_name}",
            confidence=1.0 if status == "auto" else 0.5,
            matched_via="orcid_search",
            status=status,
        )

    def _build_match_from_ror(
        self,
        org: dict[str, Any],
        matched_via: str,
        confidence: float = 1.0,
        status: str = "auto",
    ) -> IdentifierMatch:
        isni = extract_isni(org)
        parent_ror, parent_name = extract_parent(org)
        return IdentifierMatch(
            ror_id=org.get("id"),
            isni_id=isni,
            org_name=get_display_name(org),
            confidence=confidence,
            matched_via=matched_via,
            parent_ror_id=parent_ror,
            parent_name=parent_name,
            status=status,
        )
