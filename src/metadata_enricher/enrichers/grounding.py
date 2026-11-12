"""Post-merge grounding check -- does what an agent extracted actually appear in the source?

Deterministic, no network, no LLM. Flags (never drops, never edits) an extracted
actor name, award number or year that cannot be found in the text the agents were
given. The prompts already say "never invent"; this is the code-level backstop
that tells a curator *which* values to look at first.

Flag-only by design, and biased hard toward NOT flagging. A false flag costs a
curator a glance; a false *drop* would throw away a correct value that the model
merely wrote differently (accent, case, abbreviation, word order, plural,
acronym vs. expansion, a typo). So a value counts as grounded if ANY of these
holds, tried cheapest first:

1. its normalized text is a substring of the normalized source;
2. at least 60% of its significant words are in the source (exact word, a
   shared 5-letter stem so "Estadística"/"Estadísticas" match, or an
   abbreviation that is a prefix of a source word: "Univ." -> "Universidad");
3. it is an acronym of words in the source, or an expansion whose initials are
   in the source ("INE" <-> "Instituto Nacional de Estadísticas");
4. a fuzzy partial match scores >= ``_FUZZY_THRESHOLD``.

What it cannot see is a *translation* ("Ministry of Finance" for "Ministerio de
Hacienda"): that is still flagged, which is the right call for an advisory flag.
"""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

from metadata_enricher.enrichers.fuzzy_matcher import fold_accents
from metadata_enricher.types import GuardrailEvent, ResourceDescription, jsonld_list_unwrap

GUARDRAIL_NAME = "grounding"

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

# Function words (Spanish + English) that carry no identifying weight in a name.
_STOPWORDS = frozenset(
    "de del la las el los y e en para por con the of and for in at a an da do das dos".split()
)

_MIN_TOKEN_LEN = 3
_COVERAGE_THRESHOLD = 0.6
_STEM_LEN = 5
_MIN_ABBREV_LEN = 4
_FUZZY_THRESHOLD = 88.0
_FUZZY_MIN_NAME_LEN = 6
# A 3-letter acronym matches *some* run of initials in any long page by chance,
# so it is only tried against the short, high-precision sources (title,
# description, hints). Longer ones are safe against the whole page.
_ACRONYM_MIN_LEN_FULL_TEXT = 4
_ACRONYM_MIN_LEN = 3
_ACRONYM_MAX_LEN = 8


def normalize_text(text: str) -> str:
    return _NON_ALNUM.sub(" ", fold_accents(text).lower()).strip()


def repair_mojibake(text: str) -> str:
    """Undo UTF-8-read-as-Latin-1 damage ("KÃ¶ppen" -> "Köppen"); else return *text* as is.

    Some catalogue exports arrive double-encoded and the model quietly repairs
    them, so comparing its output to the raw source would look like a deviation.
    Only text carrying the telltale lead bytes is touched, and only when the
    round trip is lossless.
    """
    if "Ã" not in text and "Â" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _flatten_strings(v)]
    return []


class _Haystack:
    """Normalized, pre-indexed source text one resource's checks run against."""

    def __init__(self, primary: str, full: str) -> None:
        # primary: short curated sources (title/description/hints/publisher...).
        # full: primary + the fetched page. Lookups that are cheap and precise
        # on short text but collide by chance on a whole page use ``primary``.
        self.primary_text = f" {normalize_text(primary)} "
        self.text = f" {normalize_text(full)} "
        self.tokens = set(self.text.split())
        self.prefixes = {t[:_STEM_LEN] for t in self.tokens if len(t) >= _STEM_LEN}
        self.years = set(_YEAR_RE.findall(full))
        self.digits_only = re.sub(r"[^0-9a-z]", "", fold_accents(full).lower())
        self._initials_full = self._initials(self.text)
        self._initials_primary = self._initials(self.primary_text)

    @staticmethod
    def _initials(text: str) -> tuple[str, str]:
        words = text.split()
        content = [w for w in words if w not in _STOPWORDS]
        return ("".join(w[0] for w in content), "".join(w[0] for w in words))

    def has_acronym_expansion(self, acronym: str, *, primary_only: bool) -> bool:
        pools = self._initials_primary if primary_only else self._initials_full
        return any(acronym in pool for pool in pools)


def build_haystack(resource: ResourceDescription) -> _Haystack:
    """Everything an agent was shown: the standard fields plus any extra input
    field (``publisher``, ``context_hints``, ...), which the prompts treat as trusted."""
    primary_parts = [resource.url or "", resource.title or "", resource.description or ""]
    primary_parts.append(resource.doi or "")
    for value in (resource.model_extra or {}).values():
        primary_parts.extend(_flatten_strings(value))
    primary = "\n".join(repair_mojibake(p) for p in primary_parts if p)
    full = primary + "\n" + repair_mojibake(resource.fetched_content or "")
    return _Haystack(primary, full)


def _token_in_source(token: str, hay: _Haystack) -> bool:
    """Exact word, shared 5-letter stem (plural/gender), or an abbreviation that is a
    prefix of a source word ("univ" -> "universidad")."""
    if token in hay.tokens:
        return True
    if len(token) >= _STEM_LEN and token[:_STEM_LEN] in hay.prefixes:
        return True
    return len(token) >= _MIN_ABBREV_LEN and any(w.startswith(token) for w in hay.tokens)


def name_is_grounded(name: str, hay: _Haystack) -> bool:
    """True if *name* is findable in the source under any lenient reading (see module doc)."""
    normalized = normalize_text(name)
    if not normalized:
        return True
    if f" {normalized} " in hay.text:
        return True

    significant = [t for t in normalized.split() if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS]
    if not significant:
        return True  # nothing distinctive to look for -- cannot judge, so do not flag

    covered = sum(1 for t in significant if _token_in_source(t, hay))
    if covered / len(significant) >= _COVERAGE_THRESHOLD:
        return True

    words = normalized.split()
    if len(words) >= 2:
        # Expansion given, acronym present in source ("Instituto Nacional de Estadisticas" -> "ine").
        content = "".join(w[0] for w in words if w not in _STOPWORDS)
        every = "".join(w[0] for w in words)
        if any(len(a) >= 2 and a in hay.tokens for a in (content, every)):
            return True
    elif _ACRONYM_MIN_LEN <= len(normalized) <= _ACRONYM_MAX_LEN:
        # Acronym given, expansion present in source.
        if hay.has_acronym_expansion(
            normalized, primary_only=len(normalized) < _ACRONYM_MIN_LEN_FULL_TEXT
        ):
            return True

    return len(normalized) >= _FUZZY_MIN_NAME_LEN and (
        fuzz.partial_ratio(normalized, hay.text) >= _FUZZY_THRESHOLD
    )


def identifier_is_grounded(value: str, hay: _Haystack) -> bool:
    """An award/project number must appear verbatim, ignoring spaces/dashes/dots/case."""
    compact = re.sub(r"[^0-9a-z]", "", fold_accents(value).lower())
    return not compact or compact in hay.digits_only


def years_are_grounded(value: str, hay: _Haystack) -> bool:
    """True if *value* carries no year, or at least one of its years appears in the source."""
    years = _YEAR_RE.findall(value)
    return not years or any(y in hay.years for y in years)


def _entry_name(entry: Any) -> str:
    if isinstance(entry, dict):
        name = entry.get("schema:name")
        if isinstance(name, str):
            return name.strip()
    return ""


def _actor_entries(fields: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(field, location, entry) for every creator/contributor/publisher/funder/affiliation."""
    found: list[tuple[str, str, dict[str, Any]]] = []

    def add(field: str, location: str, entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        found.append((field, location, entry))
        affiliations = entry.get("schema:affiliation")
        if isinstance(affiliations, list):
            for i, affil in enumerate(affiliations):
                add(field, f"{location}.schema:affiliation[{i}]", affil)

    for i, creator in enumerate(jsonld_list_unwrap(fields.get("schema:creator"))):
        add("schema:creator", f"schema:creator[{i}]", creator)

    add("schema:publisher", "schema:publisher", fields.get("schema:publisher"))

    contributors = fields.get("schema:contributor")
    if isinstance(contributors, list):
        for i, entry in enumerate(contributors):
            # Role-wrapped: {"@type": ["schema:Role"], "schema:contributor": {actor}}
            inner = entry.get("schema:contributor") if isinstance(entry, dict) else None
            add("schema:contributor", f"schema:contributor[{i}]", inner if inner else entry)

    funding = fields.get("schema:funding")
    if isinstance(funding, list):
        for i, grant in enumerate(funding):
            if isinstance(grant, dict):
                add("schema:funding", f"schema:funding[{i}].schema:funder", grant.get("schema:funder"))
    return found


def check_grounding(fields: dict[str, Any], resource: ResourceDescription) -> list[GuardrailEvent]:
    """Return one ``flagged`` event per extracted value not findable in *resource*.

    *fields* is ``MetadataDocument.fields``. Never mutates it. Run it BEFORE any
    enricher/backfill that legitimately adds values from outside the source
    (Crossref DOI backfill, ROR/ISNI/ORCID identifiers).
    """
    hay = build_haystack(resource)
    events: list[GuardrailEvent] = []

    def flag(field: str, location: str, value: str, detail: str) -> None:
        events.append(
            GuardrailEvent(
                guardrail=GUARDRAIL_NAME,
                action="flagged",
                field=field,
                location=location,
                value=value[:200],
                detail=detail,
            )
        )

    for field, location, entry in _actor_entries(fields):
        name = _entry_name(entry)
        if name and not name_is_grounded(name, hay):
            flag(field, location, name, "name not found in source text")

    funding = fields.get("schema:funding")
    if isinstance(funding, list):
        for i, grant in enumerate(funding):
            ident = grant.get("schema:identifier") if isinstance(grant, dict) else None
            award = ident.get("schema:value") if isinstance(ident, dict) else None
            if isinstance(award, str) and award and not identifier_is_grounded(award, hay):
                flag(
                    "schema:funding",
                    f"schema:funding[{i}].schema:identifier",
                    award,
                    "award identifier not found verbatim in source text",
                )

    for field in ("schema:datePublished", "schema:dateCreated", "schema:copyrightYear"):
        value = fields.get(field)
        if isinstance(value, str) and value and not years_are_grounded(value, hay):
            flag(field, field, value, "no year of this date appears in source text")

    return events
