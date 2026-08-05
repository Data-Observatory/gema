"""IANA Media Type normalizer with auto-refresh from IANA XML registry.

Provides deterministic normalization of media type (MIME) strings against the
IANA media types registry. Uses a bundled JSON snapshot with automatic
background refresh to ~/.cache/proj-metadata-agents/.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

IANA_XML_URL = "https://www.iana.org/assignments/media-types/media-types.xml"
IANA_NS = {"ian": "http://www.iana.org/assignments"}
CACHE_FILENAME = "iana_media_types.json"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "proj-metadata-agents"
STALE_DAYS = 30


class IANANormalizer:
    """Normalizes format strings against the IANA media types registry.

    Loads a bundled JSON snapshot by default. Checks for a fresher cached
    version in ~/.cache/proj-metadata-agents/. Auto-refreshes from the IANA
    XML registry if the cache is older than 30 days.

    Unknown MIME types are preserved unchanged — never nulled, never errored.
    """

    def __init__(
        self,
        bundled_path: str | None = None,
        cache_dir: str | None = None,
    ) -> None:
        """Initialize the normalizer.

        Args:
            bundled_path: Path to the bundled IANA JSON snapshot.
                          If None, resolves via importlib.resources against
                          the installed metadata_enricher package — this
                          works from an editable checkout, a built wheel, and
                          a PyInstaller-frozen bundle alike, unlike a
                          repo-root-relative path.
            cache_dir: Directory for cached data. Defaults to
                       ~/.cache/proj-metadata-agents/.
        """
        if bundled_path is None:
            bundled_path = str(
                resources.files("metadata_enricher") / "data" / "iana_media_types.json"
            )

        if cache_dir is None:
            cache_dir = str(DEFAULT_CACHE_DIR)

        self._cache_dir = Path(cache_dir)
        self._cache_path = self._cache_dir / CACHE_FILENAME

        self.types: dict[str, dict[str, str]] = {}
        self.name_lookup: dict[str, str] = {}

        data = self._load_bundled(bundled_path)
        data = self._maybe_use_cache(data)
        self._apply_data(data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(self, format_value: str) -> str:
        """Normalize a format string to its canonical IANA template.

        Steps:
        1. Strip whitespace and trailing semicolons.
        2. If empty after trimming, return the empty string as-is.
        3. Split on ``;`` and take the first part (discard MIME parameters
           like ``charset=utf-8``).
        4. Lowercase the result.
        5. If exact match in ``self.types`` → return the canonical template.
        6. If not found, try ``self.name_lookup`` by short name.
        7. If still not found → return original value unchanged, log warning.

        Args:
            format_value: Raw format string (may include parameters, case
                          variations, extra whitespace).

        Returns:
            Canonical MIME template if recognized, otherwise the trimmed
            original value unchanged.
        """
        trimmed = format_value.strip().rstrip(";")
        if not trimmed:
            return format_value

        # Split on ';' to strip parameters like "text/html; charset=utf-8"
        mime_part = trimmed.split(";", 1)[0].strip()
        key = mime_part.lower()

        # 1) Exact match in types
        if key in self.types:
            return self.types[key]["template"]

        # 2) Try name_lookup (e.g., "pdf" → "application/pdf")
        if key in self.name_lookup:
            canonical = self.name_lookup[key]
            if canonical in self.types:
                return self.types[canonical]["template"]

        # 3) Unknown — preserve original
        logger.warning(
            "Unknown MIME type '%s' — preserving original value unchanged",
            key,
        )
        return mime_part

    def is_valid(self, format_value: str) -> bool:
        """Check whether *format_value* resolves to a known IANA type.

        Normalization steps 1-4 from ``normalize()`` are applied before the
        lookup.

        Args:
            format_value: Raw format string to validate.

        Returns:
            ``True`` if the normalized value is found in ``self.types``.
        """
        trimmed = format_value.strip().rstrip(";")
        if not trimmed:
            return False

        mime_part = trimmed.split(";", 1)[0].strip()
        key = mime_part.lower()

        if key in self.types:
            return True

        if key in self.name_lookup:
            canonical = self.name_lookup[key]
            return canonical in self.types

        return False

    def refresh_data(self) -> bool:
        """Fetch current IANA media types XML and rebuild in-memory lookups.

        Downloads from ``https://www.iana.org/assignments/media-types/media-types.xml``,
        parses the XML (stdlib only), saves a fresh JSON snapshot to the
        cache directory, and updates ``self.types`` / ``self.name_lookup``.

        Returns:
            ``True`` on success, ``False`` if the fetch or parse failed
            (in-memory data is left unchanged on failure).
        """
        try:
            xml_text = self._fetch_iana_xml()
            data = self._parse_iana_xml(xml_text)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._apply_data(data)
            logger.info(
                "IANA data refreshed — %d types, %d name lookups cached",
                data["_metadata"]["count"],
                len(data["name_lookup"]),
            )
            return True
        except Exception:
            logger.exception("Failed to refresh IANA media types data")
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_data(self, data: dict[str, Any]) -> None:
        """Apply loaded data dict to in-memory lookups."""
        self.types = cast(dict[str, dict[str, str]], data.get("types", {}))
        self.name_lookup = cast(dict[str, str], data.get("name_lookup", {}))

    def _load_bundled(self, bundled_path: str) -> dict[str, Any]:
        """Load the bundled JSON snapshot."""
        try:
            with open(bundled_path, encoding="utf-8") as f:
                return cast(dict[str, Any], json.load(f))
        except FileNotFoundError:
            logger.warning(
                "Bundled IANA data not found at '%s' — using empty lookups",
                bundled_path,
            )
            return {"types": {}, "name_lookup": {}}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load bundled IANA data from '%s': %s — using empty lookups",
                bundled_path,
                exc,
            )
            return {"types": {}, "name_lookup": {}}

    def _maybe_use_cache(self, bundled_data: dict[str, Any]) -> dict[str, Any]:
        """Check cache and return fresher data if available and non-stale.

        Logic:
        - If cached JSON exists and ``_metadata.last_updated`` is < STALE_DAYS
          old → use cached data.
        - If cached JSON is stale → attempt refresh, fall back to bundle on
          failure.
        - If no cache → use bundled data as-is (no auto-refresh on first init).
        """
        if not self._cache_path.exists():
            return bundled_data

        try:
            with open(self._cache_path, encoding="utf-8") as f:
                cached: dict[str, Any] = json.load(f)
            last_updated_str = cached.get("_metadata", {}).get("last_updated")
            if last_updated_str:
                last_updated = datetime.fromisoformat(last_updated_str)
                cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
                if last_updated > cutoff:
                    logger.debug("Using cached IANA data (updated %s)", last_updated_str)
                    return cached
                else:
                    logger.info(
                        "Cached IANA data is stale (updated %s) — refreshing",
                        last_updated_str,
                    )
                    refreshed = self._try_refresh()
                    if refreshed:
                        return refreshed
                    # Refresh failed — fall through to bundled
                    logger.warning("Refresh failed, falling back to bundled IANA data")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read cached IANA data: %s", exc)

        return bundled_data

    def _try_refresh(self) -> dict[str, Any] | None:
        """Attempt a single refresh and return the new data dict on success."""
        try:
            xml_text = self._fetch_iana_xml()
            data = self._parse_iana_xml(xml_text)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return data
        except Exception:
            logger.exception("IANA refresh attempt failed")
            return None

    @staticmethod
    def _fetch_iana_xml() -> str:
        """Fetch the IANA media types XML via httpx."""
        response = httpx.get(
            IANA_XML_URL,
            headers={"User-Agent": "proj-metadata-agents/1.0"},
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse_iana_xml(xml_text: str) -> dict[str, Any]:
        """Parse IANA media types XML into the standard JSON structure.

        Mirrors the logic in ``scripts/generate_iana_data.py``.
        """
        root = ET.fromstring(xml_text)

        types: dict[str, dict[str, str]] = {}
        type_breakdown: dict[str, int] = defaultdict(int)

        for registry in root.findall("ian:registry", IANA_NS):
            registry_id = registry.get("id", "unknown")
            for record in registry.findall("ian:record", IANA_NS):
                name_elem = record.find("ian:name", IANA_NS)
                if name_elem is None or not name_elem.text:
                    continue
                subtype_name = name_elem.text.strip()

                template = None
                for file_elem in record.findall("ian:file", IANA_NS):
                    if file_elem.get("type") == "template":
                        template = (file_elem.text or "").strip()
                        break

                if not template:
                    template = f"{registry_id}/{subtype_name}"

                reference = _parse_reference(record, IANA_NS)

                types[template] = {
                    "name": subtype_name,
                    "template": template,
                    "reference": reference,
                }
                type_breakdown[registry_id] += 1

        name_lookup = _deduplicate_name_lookup(types)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "_metadata": {
                "last_updated": now,
                "source": "IANA",
                "count": len(types),
            },
            "types": types,
            "name_lookup": name_lookup,
        }


# ------------------------------------------------------------------
# Shared XML helpers (package-private, reused from generate_iana_data)
# ------------------------------------------------------------------


def _parse_reference(record: ET.Element, ns: dict[str, str]) -> str:
    """Extract a reference string from a record's xref elements."""
    xrefs = record.findall("ian:xref", ns)
    if not xrefs:
        return ""

    references = []
    for x in xrefs:
        ref_type = x.get("type", "")
        ref_data = x.get("data", "")
        text = (x.text or "").strip()

        if ref_type == "rfc":
            ref = ref_data.upper()
            if not ref.startswith("RFC"):
                ref = "RFC " + ref[3:]
            references.append(ref)
        elif ref_type == "person":
            references.append(ref_data.replace("_", " "))
        elif ref_type == "uri":
            references.append(text or ref_data)
        elif ref_type == "draft":
            references.append(ref_data.replace("RFC-", ""))
        elif ref_type == "rfc-errata":
            references.append(f"RFC Errata {ref_data}")
        elif ref_type == "registry":
            references.append(f"Registry: {ref_data}")
        else:
            references.append(text or ref_data)

    ref_str = "; ".join(references) if references else ""
    return ref_str.strip()


def _deduplicate_name_lookup(types: dict[str, dict[str, str]]) -> dict[str, str]:
    """Build name_lookup keeping only short names that map to exactly one type."""
    name_to_types: dict[str, list[str]] = defaultdict(list)
    for full_type in types:
        if "/" in full_type:
            short = full_type.split("/", 1)[1].lower()
            name_to_types[short].append(full_type)

    lookup: dict[str, str] = {}
    for short_name, full_types in name_to_types.items():
        if len(full_types) == 1:
            lookup[short_name] = full_types[0]
    return lookup
