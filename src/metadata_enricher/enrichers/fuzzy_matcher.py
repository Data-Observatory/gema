"""Fuzzy organization name matching using rapidfuzz.

Provides pure utility functions for normalizing organization names and
matching them against candidate lists with threshold filtering and
ambiguity detection.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

# Common legal/organizational suffixes to strip during normalization.
# Matches as whole words at end-of-string, optionally followed by a period.
_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|ltd|limited|llc|gmbh|corp|corporation|sa|s\.a\.|nv|bv|plc|pty|pte|"
    r"spa|ag|kg|oyj|ab|as|aps|srl|sarl|bvba|nvsa)\b\.?\s*$",
    re.IGNORECASE,
)

# Punctuation to remove (keep word chars, whitespace, and hyphens).
_PUNCTUATION = re.compile(r"[^\w\s-]")

# Collapse multiple whitespace characters.
_WHITESPACE = re.compile(r"\s+")


def normalize_org_name(name: str) -> str:
    """Normalize an organization name for matching and cache keys.

    Steps:
    1. Strip whitespace
    2. Lowercase
    3. Remove common legal suffixes (inc, ltd, llc, gmbh, corp, etc.)
    4. Remove punctuation (keep hyphens and alphanumeric)
    5. Collapse multiple spaces to single space
    6. Strip again

    Args:
        name: Raw organization name (may have suffixes, mixed case, punctuation).

    Returns:
        Normalized name string suitable for comparison and cache keys.

    Examples:
        >>> normalize_org_name("Harvard University, Inc.")
        'harvard university'
        >>> normalize_org_name("MIT")
        'mit'
        >>> normalize_org_name("Universidad de Chile")
        'universidad de chile'
    """
    if not name:
        return ""

    name = name.strip()
    name = name.lower()
    name = _LEGAL_SUFFIXES.sub("", name)
    name = _PUNCTUATION.sub("", name)
    name = _WHITESPACE.sub(" ", name)
    return name.strip()


def match_organization(
    query: str,
    candidates: list[dict[str, Any]],
    name_key: str = "name",
    threshold: float = 90.0,
    gap_threshold: float = 5.0,
    country_hint: str | None = None,
    country_key: str = "country_code",
    country_penalty: float = 15.0,
) -> tuple[dict[str, Any] | None, float, str]:
    """Match an organization name against a list of candidate dicts.

    Uses rapidfuzz ``process.extract`` with ``fuzz.WRatio`` scorer (auto-selects
    best strategy per pair: token_set_ratio, token_sort_ratio, partial_ratio, or
    weighted ratio).

    Args:
        query: Organization name to match.
        candidates: List of candidate dicts (e.g. ROR/ISNI records).
        name_key: Key in each candidate dict that holds the name to compare.
        threshold: Minimum score (0-100) for a valid match. Default 90.0.
        gap_threshold: If the gap between top-1 and top-2 scores is less than
                       this, the match is flagged as ``"review"``. Default 5.0.
        country_hint: Optional ISO 3166-1 alpha-2 country code (e.g. from
                      ``country_extractor``). A HINT, not a gate — a candidate
                      whose own country disagrees is deprioritized by
                      *country_penalty* points, never eliminated outright.
                      A candidate with no known country (missing/empty
                      *country_key*) is never penalized — unknown is not a
                      disagreement. ``None`` (default) disables this entirely.
        country_key: Key in each candidate dict holding its own country code,
                     compared case-insensitively against *country_hint*.
        country_penalty: Score points subtracted from a country-mismatched
                         candidate before ranking, when *country_hint* is set.

    Returns:
        Tuple of ``(best_candidate_dict_or_None, score, status)`` where status
        is one of:
        - ``"auto"``: Unambiguous match (score >= threshold, gap >= gap_threshold)
        - ``"review"``: Ambiguous match (score >= threshold, gap < gap_threshold)
        - ``"nomatch"``: No match found (score < threshold or no candidates)

    Examples:
        >>> candidates = [{"name": "Harvard University", "id": "X"}]
        >>> mat, score, status = match_organization("Harvard", candidates)
        >>> status
        'auto'
    """
    if not candidates or not query.strip():
        return None, 0.0, "nomatch"

    normalized_query = normalize_org_name(query)
    candidate_names = [
        normalize_org_name(str(c.get(name_key, ""))) for c in candidates
    ]

    # Without a country hint, only the top 2 are needed (existing fast path,
    # unchanged). With a hint, every candidate must be scored first so the
    # country penalty can re-rank the full field before picking the top 2.
    limit = len(candidate_names) if country_hint else 2
    results = process.extract(
        normalized_query,
        candidate_names,
        scorer=fuzz.WRatio,
        limit=limit,
        score_cutoff=threshold - 10,
    )

    if not results:
        return None, 0.0, "nomatch"

    if country_hint:
        hint = country_hint.strip().upper()
        adjusted: list[tuple[str, float, int]] = []
        for name, score, idx in results:
            candidate_country = candidates[idx].get(country_key)
            mismatch = (
                isinstance(candidate_country, str)
                and candidate_country.strip().upper() not in ("", hint)
            )
            adjusted.append((name, score - country_penalty if mismatch else score, idx))
        adjusted.sort(key=lambda r: r[1], reverse=True)
        results = adjusted[:2]

    best_match_str, best_score, best_idx = results[0]

    if best_score < threshold:
        return None, best_score, "nomatch"

    best_candidate = candidates[best_idx]

    if len(results) < 2:
        return best_candidate, best_score, "auto"

    _, second_score, _ = results[1]
    gap = best_score - second_score

    if gap < gap_threshold:
        return best_candidate, best_score, "review"

    return best_candidate, best_score, "auto"
