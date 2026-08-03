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
from metadata_enricher.enrichers.ror_client import (
    RORClient,
    extract_isni,
    extract_parent,
    get_display_name,
)

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "metagen" / "identifiers"
DEFAULT_TTL = timedelta(days=30)


class IdentifierResolver:
    """Resolves organization names to ROR/ISNI identifiers via a fallback chain.

    Resolution order:
    1. Check disk cache (key = SHA-256 of normalized name).
    2. ROR ?affiliation= endpoint — if chosen:true, return immediately.
    3. ROR ?query= endpoint + rapidfuzz fuzzy matching (threshold 90).
    4. ISNI SRU pica.nw search + fuzzy matching.
    5. Return None (cached as negative result).

    All API failures are caught and logged — the resolver never raises.
    Negative results (None) are cached to avoid repeated API calls.
    """

    def __init__(
        self,
        ror_client: RORClient | None = None,
        isni_client: ISNIClient | None = None,
        cache_dir: Path | None = None,
        cache_ttl: timedelta = DEFAULT_TTL,
        fuzzy_threshold: float = 90.0,
    ) -> None:
        self._ror = ror_client or RORClient()
        self._isni = isni_client or ISNIClient()
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

        cache_key = self._make_key(normalized)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if cached.get("__negative__"):
                return None
            return IdentifierMatch.model_validate(cached)

        result = self._try_resolve(name, normalized)

        if result is not None:
            self._cache.set(cache_key, result.model_dump(), expire=self._cache_ttl)
        else:
            self._cache.set(cache_key, {"__negative__": True}, expire=self._cache_ttl)

        return result

    def close(self) -> None:
        self._cache.close()
        self._ror.close()
        self._isni.close()

    def __enter__(self) -> IdentifierResolver:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _make_key(self, normalized_name: str) -> str:
        return hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()

    def _try_resolve(self, original_name: str, normalized_name: str) -> IdentifierMatch | None:
        result = self._try_ror_affiliation(original_name)
        if result is not None:
            return result

        result = self._try_ror_query(original_name, normalized_name)
        if result is not None:
            return result

        result = self._try_isni(original_name, normalized_name)
        if result is not None:
            return result

        return None

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
