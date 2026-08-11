"""Best-effort live URL fetching to populate ``ResourceDescription.fetched_content``.

Several DataCite fields (dates, media_files, related_identifiers, geo hints)
genuinely live only on the destination page, not in a short title/description
— a controlled A/B eval (see ``scripts/fetch_content.py``, the eval-only
harness this module was ported from) showed a clean, consistent structural-
accuracy improvement across every model tested when the page's cleaned text
was fed into the agent prompts via ``fetched_content``.

This module is production code, gated behind ``PipelineConfig.enable_content_
fetch`` (default ``False``) and wired in ``pipeline.py``. It must never raise:
a failed/slow/dead URL just means no ``fetched_content`` for that resource,
identical to today's behavior when the caller doesn't supply one — never
blocks generation.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_STRIP_BLOCKS_RE = re.compile(r"(?is)<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_BARE_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

USER_AGENT = "Mozilla/5.0 (compatible; metagen/1.0)"


def _resolve_url(url: str) -> str:
    """Resolve a bare DOI (e.g. "10.5880/gfz.4.1.2020.012") through doi.org.

    Some corpora store identifiers as bare DOIs with no URL scheme — a plain
    GET on that fails outright. Resolve it the same way any DOI resolver
    would, by prefixing the canonical doi.org redirect.
    """
    if _BARE_DOI_RE.match(url):
        return f"https://doi.org/{url}"
    return url


def clean_html_to_text(html: str, max_len: int = 8000) -> str:
    """Strip script/style/nav/header/footer blocks and all remaining tags,
    collapse whitespace, truncate to *max_len*.

    Not a full readability algorithm — real page nav/breadcrumb text often
    survives alongside real content, but the agent prompts already instruct
    hunting for specific facts (dates, file links) in whatever text they're
    given, so noise is tolerable.
    """
    html = _STRIP_BLOCKS_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_len]


def fetch_page_content(url: str, *, timeout: float = 15.0, max_len: int = 8000) -> str | None:
    """Best-effort live fetch + clean of *url*.

    Returns ``None`` on any failure (empty url, non-200, timeout, connection
    error, non-HTML/text content-type) — callers must treat this as purely
    optional and never let it block resource processing.
    """
    if not url:
        return None
    resolved_url = _resolve_url(url)
    try:
        response = httpx.get(
            resolved_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        logger.warning("fetch failed for %s: %s", resolved_url, exc)
        return None
    except Exception as exc:  # defensive: never let a fetch failure propagate
        logger.warning("fetch failed for %s: %s", resolved_url, exc)
        return None

    if response.status_code != 200:
        logger.warning("fetch non-200 for %s: %s", resolved_url, response.status_code)
        return None

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        logger.warning("fetch non-HTML content-type for %s: %s", resolved_url, content_type)
        return None

    text = clean_html_to_text(response.text, max_len=max_len)
    return text or None
