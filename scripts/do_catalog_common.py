"""do_catalog-specific ground-truth adaptation and scoring extensions.

The one genuinely corpus-specific module in this eval toolchain, because
there is exactly one real external data source (the ``do-catalog-resources``
S3 bucket) with one real shape quirk to adapt: top-level ``roles`` (a single
list with a ``type`` discriminator — ``"Creator"``/``"Contributor"``) instead
of the current schema's ``creators`` list. ``media_files`` and
``geo_locations``/``temporal_events`` field *names* already match the current
schema closely (verified this session) — no adapter needed for those, and
none is provided here; adding one would be dead code.
"""

from __future__ import annotations

import re
from typing import Any

import eval_common

# Schemes actually present in the do_catalog corpus's identifiers (confirmed
# this session, sampling MM=04): mostly VIAF/Wikidata (publishers) and ISNI
# (creators), with ROR genuinely rare. eval_common.extract_ror_ids is
# ROR-only by design (matches Geoportal-style clean ground truth) — scoring
# do_catalog against that alone would zero out `ror_match` for correctly
# resolving a proper ROR the truth simply doesn't happen to carry. This
# module's identifier_match_score is scheme-aware instead: credit a match
# against whichever scheme the truth actually provides.
IDENTIFIER_SCHEMES = frozenset({"ROR", "ISNI", "VIAF", "Wikidata"})


def adapt_ground_truth(attrs: dict[str, Any]) -> dict[str, Any]:
    """Preprocessing normalizer producing a dict eval_common.py's extract_*
    functions can consume as-is. Does not touch those functions.

    Maps BOTH roles[].type == "Creator" and == "Contributor" into the current
    schema's unified `creators` list — schemas/datacite.py's
    _normalize_creators already supports a `contributor_type` sub-field per
    creator entry, so creators and contributors already unify into one list
    in the current schema; this just carries that same unification back onto
    the legacy `roles` shape.
    """
    adapted = dict(attrs)
    creators: list[dict[str, Any]] = []
    for r in attrs.get("roles", []):
        role_type = r.get("type")
        if role_type not in ("Creator", "Contributor"):
            continue
        creators.append({
            "creator_name": r.get("role_name", ""),
            "creator_name_type": r.get("role_name_type", ""),
            "given_name": r.get("given_name", ""),
            "family_name": r.get("family_name", ""),
            "name_identifiers": r.get("name_identifiers", []),
            "affiliations": r.get("affiliations", []),
            "contributor_type": r.get("contributor_type", "") if role_type == "Contributor" else "",
        })
    adapted["creators"] = creators

    # `roles` must be dropped, not left alongside `creators`: if it stayed,
    # extract_populated_fields()'s field-coverage metric would never credit
    # `creators` coverage (pipeline output never has a `roles` key) and would
    # spuriously penalize every model equally for a truth-key they can never
    # match by construction. `origin_name`/`origin_priority` are catalog
    # bookkeeping, not DataCite content at all — drop unconditionally.
    adapted.pop("roles", None)
    adapted.pop("origin_name", None)
    adapted.pop("origin_priority", None)
    return adapted


def _norm(s: str) -> str:
    return s.strip().lower()


_ISNI_PREFIX_RE = re.compile(r"^https?://isni\.org/isni/")
_ROR_PREFIX_RE = re.compile(r"^https?://ror\.org/")
_ORCID_PREFIX_RE = re.compile(r"^https?://orcid\.org/")


def _normalize_identifier_value(scheme: str, value: str) -> str:
    """Normalize an identifier value for scheme-aware set comparison.

    Ground truth and pipeline output disagree on identifier *shape*, not just
    case/whitespace, for ROR/ISNI/ORCID: truth sometimes wraps a value in its
    canonical resolver URL (e.g. ISNI as
    ``https://isni.org/isni/0000000122238173``), while ``IdentifierEnricher``
    (``src/metadata_enricher/enrichers/identifier_types.py``) emits ISNI as
    bare digits and ORCID as a bare dash-grouped id — only ROR is
    URI-wrapped on the pipeline side. Strip each scheme's own URI wrapper
    before comparing, so a truth URI and a pipeline bare value for the same
    real-world identifier land on the same normalized form.
    """
    value = _norm(value)
    if scheme == "ISNI":
        value = _ISNI_PREFIX_RE.sub("", value)
        return re.sub(r"[^0-9x]", "", value)
    if scheme == "ROR":
        return _ROR_PREFIX_RE.sub("", value).rstrip("/")
    if scheme == "ORCID":
        return _ORCID_PREFIX_RE.sub("", value)
    return value


def extract_identifiers(attrs: dict[str, Any], schemes: frozenset[str]) -> set[tuple[str, str]]:
    """Scheme-aware identifier set across creators' name_identifiers,
    creators' affiliations, and publishers — (scheme, normalized_value)
    pairs, restricted to *schemes*."""
    ids: set[tuple[str, str]] = set()
    for c in attrs.get("creators", []):
        for nid in c.get("name_identifiers", []):
            scheme = nid.get("name_identifier_scheme", "")
            val = _normalize_identifier_value(scheme, nid.get("name_identifier", ""))
            if val and scheme in schemes:
                ids.add((scheme, val))
        for aff in c.get("affiliations", []):
            scheme = aff.get("affiliation_identifier_scheme", "")
            val = _normalize_identifier_value(scheme, aff.get("affiliation_identifier", ""))
            if val and scheme in schemes:
                ids.add((scheme, val))
    for p in attrs.get("publishers", []):
        scheme = p.get("publisher_identifier_scheme", "")
        val = _normalize_identifier_value(scheme, p.get("publisher_identifier", ""))
        if val and scheme in schemes:
            ids.add((scheme, val))
    return ids


def identifier_match_score(
    truth: dict[str, Any], actual: dict[str, Any], schemes: frozenset[str] = IDENTIFIER_SCHEMES
) -> float:
    """Same semantics as eval_common.extract_ror_ids-based scoring (1.0 if
    truth has none and actual hallucinated none; 0.0 if actual hallucinated
    when truth has none; else overlap ratio) — just scheme-aware instead of
    ROR-only."""
    truth_ids = extract_identifiers(truth, schemes)
    actual_ids = extract_identifiers(actual, schemes)
    if truth_ids:
        return len(truth_ids & actual_ids) / len(truth_ids)
    if actual_ids:
        return 0.0
    return 1.0


def orcid_match_score(truth: dict[str, Any], actual: dict[str, Any]) -> float:
    """ORCID-scheme-only — meaningful signal only on the ORCID slice (the
    main corpus has essentially zero Personal creators to begin with, so this
    will trivially read 1.0 there). Reported alongside, not folded into
    compare_outputs()'s `overall` — adding a 10th weighted metric would
    require re-normalizing eval_common.WEIGHTS, a bigger change than "extend
    scoring for do_catalog" calls for."""
    return identifier_match_score(truth, actual, frozenset({"ORCID"}))


def compare_outputs(truth: dict[str, Any], actual: dict[str, Any]) -> dict[str, float]:
    """eval_common.compare_outputs(), with `ror_match` replaced by the
    scheme-aware identifier_match_score (and `overall` recomputed to match),
    plus `orcid_match` added as an extra informational field."""
    scores = eval_common.compare_outputs(truth, actual)
    scores["ror_match"] = identifier_match_score(truth, actual)
    scores["overall"] = sum(scores[k] * w for k, w in eval_common.WEIGHTS.items())
    scores["orcid_match"] = orcid_match_score(truth, actual)
    return scores
