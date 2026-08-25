"""Human-curated ROR/ISNI override store — checked before any network call.

Turns ``scripts/curate_ror_isni.py``'s review-file output into a durable,
reusable input instead of a one-off artifact (see BACKLOG.md's "Identifier
enrichment" section — the human-curation step it was built for). Fails soft
throughout, same as every other enricher here: a missing, empty, or
malformed file means "no overrides applied," never a pipeline-aborting
exception.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from metadata_enricher.enrichers.fuzzy_matcher import normalize_org_name
from metadata_enricher.enrichers.identifier_types import IdentifierMatch

logger = logging.getLogger(__name__)


class IdentifierOverrides:
    """Looks up a human-curated identifier match by ``(normalized name, country)``.

    File format (YAML)::

        overrides:
          - name: "Ministerio de Salud"     # as normally written; normalized internally
            country: "CL"                    # ISO 3166-1 alpha-2, or omit for any country
            ror_id: "https://ror.org/xxxxxxx"
            isni_id: null                     # optional

    Keyed on ``(normalized_name, country)`` so the same name in two
    countries never collides — e.g. "Ministerio de Salud" resolving to a
    different ROR per country. An entry with no ``country`` matches any
    country, checked only after a country-specific entry misses.
    """

    def __init__(self, path: Path | None) -> None:
        self._by_key: dict[tuple[str, str | None], IdentifierMatch] = {}
        if path is None:
            return
        if not path.is_file():
            logger.debug("Identifier overrides file not found, skipping: %s", path)
            return
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse identifier overrides file %s: %s", path, exc)
            return
        if not isinstance(raw, dict):
            return
        entries = raw.get("overrides", [])
        if not isinstance(entries, list):
            logger.warning(
                "Identifier overrides file %s: 'overrides' is not a list, ignoring", path
            )
            return
        for entry in entries:
            self._load_entry(entry, path)

    def _load_entry(self, entry: Any, path: Path) -> None:
        if not isinstance(entry, dict):
            logger.warning("Identifier overrides file %s: skipping non-dict entry: %r", path, entry)
            return
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            logger.warning(
                "Identifier overrides file %s: entry missing 'name', skipping: %r", path, entry
            )
            return
        normalized = normalize_org_name(name)
        if not normalized:
            return
        country = entry.get("country")
        country_key = country.strip().upper() if isinstance(country, str) and country.strip() else None
        ror_id = entry.get("ror_id") or None
        isni_id = entry.get("isni_id") or None
        if not ror_id and not isni_id:
            logger.warning(
                "Identifier overrides file %s: entry %r has neither ror_id nor isni_id, skipping",
                path,
                name,
            )
            return
        self._by_key[(normalized, country_key)] = IdentifierMatch(
            ror_id=ror_id,
            isni_id=isni_id,
            org_name=name,
            confidence=1.0,
            matched_via="override",
            status="auto",
        )

    def lookup(self, name: str, country: str | None = None) -> IdentifierMatch | None:
        """A curated match for *name* (+ optional *country*), or None."""
        if not self._by_key or not name:
            return None
        normalized = normalize_org_name(name)
        if not normalized:
            return None
        country_key = country.strip().upper() if country else None
        if country_key is not None:
            match = self._by_key.get((normalized, country_key))
            if match is not None:
                return match
        return self._by_key.get((normalized, None))
