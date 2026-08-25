"""Fuzzy organization name matching using rapidfuzz.

Provides pure utility functions for normalizing organization names and
matching them against candidate lists with threshold filtering and
ambiguity detection.
"""

from __future__ import annotations

import logging
import re
import unicodedata
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

# Spanish institutional-abbreviation forms common in the Chilean/LatAm
# government-data corpus this project targets (see CLAUDE.md). Deliberately
# NOT a hardcoded acronym -> full-name dictionary (e.g. "UdeC" -> "Universidad
# de Concepción") — that requires verified institutional ground truth this
# function has no way to check, and belongs in the curated overrides store
# (enrichers/identifier_overrides.py) instead, matching this project's stance
# against ungrounded invented institutional facts (see BACKLOG.md). Only
# Spanish forms are covered — gema's corpus is Chilean/Spanish-primary;
# Portuguese-specific abbreviations aren't included since there's no real
# Portuguese-corpus data here to verify them against. Accent folding below
# already normalizes most Spanish/Portuguese spelling differences for free
# (e.g. "Ministério"/"Ministerio" both fold to the same token) without
# needing a language-specific rule.
_ABBREVIATIONS: dict[str, str] = {
    # "u." alone (not "u. de") is deliberately excluded -- it collides with
    # the bare "U." in "U.S.", "U.K.", "U.N.", "U.E." and similar, which are
    # plausible in an org name too (confirmed by a real false-positive on
    # "U.S.-Chile" during testing: bare "u." expanded to "universidad" mid-word).
    "u. de": "universidad de",
    "univ.": "universidad",
    "min.": "ministerio",
    "inst.": "instituto",
    "dept.": "departamento",
    "depto.": "departamento",
    "mun.": "municipalidad",
    "gob.": "gobierno",
    "subsec.": "subsecretaria",
    "serv.": "servicio",
}

# Longest-first alternation so "univ." matches whole, not as a shorter key's
# stray leftover. Internal whitespace in a multi-word key (e.g. "u. de")
# matches \s+, not a literal single space -- messy input hasn't had its
# whitespace collapsed yet at this point in normalize_org_name.
_ABBREVIATION_RE = re.compile(
    r"\b("
    + "|".join(
        r"\s+".join(re.escape(part) for part in key.split(" "))
        for key in sorted(_ABBREVIATIONS, key=len, reverse=True)
    )
    + r")",
    re.IGNORECASE,
)

# Punctuation to remove (keep word chars, whitespace, and hyphens).
_PUNCTUATION = re.compile(r"[^\w\s-]")

# Collapse multiple whitespace characters.
_WHITESPACE = re.compile(r"\s+")


def fold_accents(name: str) -> str:
    """NFKD-normalize and drop combining marks, e.g. 'Educación' -> 'educacion'.

    Locale-agnostic (unlike the abbreviation dict above) — benefits Spanish
    and Portuguese alike. The canonical implementation of this technique in
    this codebase — ``scripts/eval_common.py``'s ``_norm()`` calls this
    directly rather than keeping its own copy, so there's one place to fix
    if a Unicode edge case ever needs it. Not adding a ``unidecode``
    dependency for something two lines of stdlib already do.
    """
    folded = unicodedata.normalize("NFKD", name)
    return "".join(c for c in folded if not unicodedata.combining(c))


def _expand_abbreviations(name: str) -> str:
    def _replace(m: re.Match[str]) -> str:
        key = re.sub(r"\s+", " ", m.group(0).lower())
        return _ABBREVIATIONS[key]

    return _ABBREVIATION_RE.sub(_replace, name)


def normalize_org_name(name: str) -> str:
    """Normalize an organization name for matching and cache keys.

    Steps:
    1. Strip whitespace
    2. Lowercase
    3. Fold accents (NFKD, drop combining marks)
    4. Expand common Spanish institutional abbreviations (u./univ./min./...)
    5. Remove common legal suffixes (inc, ltd, llc, gmbh, corp, etc.)
    6. Remove punctuation (keep hyphens and alphanumeric)
    7. Collapse multiple spaces to single space
    8. Strip again

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
        >>> normalize_org_name("U. de Concepción")
        'universidad de concepcion'
    """
    if not name:
        return ""

    name = name.strip()
    name = name.lower()
    name = fold_accents(name)
    name = _expand_abbreviations(name)
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
