"""Extract country code from HTML metadata and/or URL hostname.

Uses only stdlib — no external dependencies.
Priority: HTML meta tags > html lang attribute > URL country-code TLD.

URL-based extraction supports ALL ~240 country-code TLDs algorithmically:
any 2-letter non-generic TLD is treated as a ccTLD and mapped to the
corresponding ISO 3166-1 alpha-2 code (uppercased). Only a small set of
exceptions (deprecated/redirected ccTLDs) are handled via explicit mapping.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

# Exceptions where the ccTLD does NOT match its ISO 3166-1 alpha-2 code.
# Most ccTLDs are the ISO code lowercased, so we handle those algorithmically.
# These are the few that diverge (deprecated/redirected ccTLDs).
_CCTLD_EXCEPTIONS: dict[str, str] = {
    "uk": "GB",  # United Kingdom
    "su": "RU",  # Soviet Union (deprecated, still in DNS)
    "tp": "TL",  # East Timor (deprecated, now .tl)
    "yu": "RS",  # Yugoslavia (deprecated)
    "cs": "RS",  # Serbia and Montenegro (deprecated)
    "zr": "CD",  # Zaire (deprecated, now .cd)
}

_GENERIC_TLDS: frozenset[str] = frozenset({"com", "org", "net", "edu", "gov", "io"})

# Precompiled regex patterns for HTML metadata extraction.
_RE_OG_LOCALE = re.compile(
    r'<meta[^>]+property=["\']og:locale["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_RE_OG_LOCALE_SWAPPED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:locale["\']',
    re.IGNORECASE,
)
_RE_GEO_COUNTRY = re.compile(
    r'<meta[^>]+name=["\']geo\.country["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_RE_GEO_COUNTRY_SWAPPED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']geo\.country["\']',
    re.IGNORECASE,
)
_RE_GEO_REGION = re.compile(
    r'<meta[^>]+name=["\']geo\.region["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_RE_GEO_REGION_SWAPPED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']geo\.region["\']',
    re.IGNORECASE,
)
_RE_HTML_LANG = re.compile(
    r'<html[^>]+lang=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_RE_HTML_LANG_SWAPPED = re.compile(
    r'<html[^>]+(?:xml:)?lang=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _extract_country_from_locale(locale: str) -> Optional[str]:
    """Extract ISO country code from a locale/language tag.

    Handles both underscore-separated locale strings ('es_CL') and
    hyphen-separated language tags ('es-CL' from html lang attribute).

    Returns the part after the last separator, uppercased, if it looks
    like a 2-letter country code.  Returns None otherwise.
    """
    if "_" in locale:
        parts = locale.rsplit("_", 1)
    elif "-" in locale:
        parts = locale.rsplit("-", 1)
    else:
        return None
    if len(parts) != 2:
        return None
    candidate = parts[1].upper()
    if re.fullmatch(r"[A-Z]{2}", candidate):
        return candidate
    return None


def _extract_country_from_region(region: str) -> Optional[str]:
    """Extract ISO country code from a geo.region string like 'CL-RM'.

    Returns the part before the hyphen, uppercased, if it looks like a
    2-letter country code.  Returns None otherwise.
    """
    if "-" not in region:
        return None
    parts = region.split("-", 1)
    candidate = parts[0].upper()
    if re.fullmatch(r"[A-Z]{2}", candidate):
        return candidate
    return None


class CountryExtractor:
    """Extract ISO 3166-1 alpha-2 country code from HTML or URL.

    Usage::

        >>> extractor = CountryExtractor()
        >>> extractor.extract_country(html, url)
        'CL'
    """

    def extract_from_html(self, html_content: str) -> Optional[str]:
        """Extract country code from HTML metadata.

        Tries sources in priority order:
        1. ``<meta property="og:locale" content="es_CL">`` → parse locale
        2. ``<meta name="geo.country" content="CL">`` → direct country code
        3. ``<meta name="geo.region" content="CL-RM">`` → first part
        4. ``<html lang="es-CL">`` → parse lang-region

        Returns None when no source yields a valid 2-letter country code.
        """
        if not html_content:
            return None

        # 1. og:locale
        m = _RE_OG_LOCALE.search(html_content) or _RE_OG_LOCALE_SWAPPED.search(
            html_content
        )
        if m:
            result = _extract_country_from_locale(m.group(1))
            if result:
                return result

        # 2. geo.country (direct two-letter code)
        m = _RE_GEO_COUNTRY.search(html_content) or _RE_GEO_COUNTRY_SWAPPED.search(
            html_content
        )
        if m:
            candidate = m.group(1).strip().upper()
            if re.fullmatch(r"[A-Z]{2}", candidate):
                return candidate

        # 3. geo.region (e.g. "CL-RM")
        m = _RE_GEO_REGION.search(html_content) or _RE_GEO_REGION_SWAPPED.search(
            html_content
        )
        if m:
            result = _extract_country_from_region(m.group(1))
            if result:
                return result

        # 4. <html lang="...">
        m = _RE_HTML_LANG.search(html_content)
        if m:
            result = _extract_country_from_locale(m.group(1))
            if result:
                return result

        return None

    def extract_from_url(self, url: str) -> Optional[str]:
        """Extract country code from a URL's hostname TLD.

        Supports ALL ~240 country-code TLDs algorithmically:
        any 2-letter non-generic TLD is treated as a ccTLD and mapped to
        its ISO 3166-1 alpha-2 code (uppercased).  A small set of exceptions
        (deprecated/redirected ccTLDs) is handled via explicit mapping.

        Skips generic TLDs (.com, .org, .net, .edu, .gov, .io) — returns None.

        Returns None when no match is found.
        """
        if not url:
            return None

        try:
            parsed = urlparse(url)
        except Exception:
            return None

        hostname = parsed.hostname
        if not hostname:
            return None

        parts = hostname.rsplit(".", 1)
        if len(parts) < 2:
            return None
        tld = parts[1].lower()

        if tld in _GENERIC_TLDS:
            return None

        # Check exceptions first (ccTLDs that don't match their ISO code).
        if tld in _CCTLD_EXCEPTIONS:
            return _CCTLD_EXCEPTIONS[tld]

        # Any other 2-letter TLD is a ccTLD → country code is TLD uppercased.
        if re.fullmatch(r"[a-z]{2}", tld):
            return tld.upper()

        return None

    def extract_country(
        self,
        html_content: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Optional[str]:
        """Extract country code, trying HTML first, then URL as fallback.

        Args:
            html_content: Full HTML page content (optional).
            url: URL string (optional).

        Returns:
            ISO 3166-1 alpha-2 country code (e.g. ``'CL'``), or None.
        """
        # HTML metadata is more reliable — try it first.
        if html_content:
            result = self.extract_from_html(html_content)
            if result:
                return result

        # Fall back to URL TLD.
        if url:
            return self.extract_from_url(url)

        return None
