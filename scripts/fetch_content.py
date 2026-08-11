"""Live URL fetching for the do_catalog reverse-input pipeline.

Populates ResourceDescription's `fetched_content` field (raw scraped page
text) — the same field the real production pipeline uses (see
`examples/sample_input01.json`, `agents/base.py`'s `_build_resource_dict`).
Our minimal {url, title, description, publisher} input never had this, and
several fields (dates, media_files, related_identifiers) genuinely live only
on the destination page, not in a short title/description — confirmed this
session on real ground-truth examples (16 specific yearly dates present in
truth, zero trace of any year in the description text). No prompt wording
fixes a gap that's about missing input, not model behavior.

Best-effort only: these are real, live, occasionally slow/dead government
URLs. A failed/empty fetch just means no `fetched_content` for that input,
matching prior behavior — never blocks generation.
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


def _resolve_url(url: str) -> str:
    """Some corpora (confirmed: do_catalog's DataCite/ORCID slice) store the
    bare DOI as `resource.identifier` — e.g. "10.5880/gfz.4.1.2020.012" —
    with no scheme, so a plain GET fails outright. Resolve it through
    doi.org, same as any DOI resolver would."""
    if _BARE_DOI_RE.match(url):
        return f"https://doi.org/{url}"
    return url

USER_AGENT = "Mozilla/5.0 (compatible; metagen-eval/1.0)"


def clean_html_to_text(html: str, max_len: int = 8000) -> str:
    """Strip script/style/nav/header/footer blocks and all remaining tags,
    collapse whitespace, truncate. Not a full readability algorithm — real
    page nav/breadcrumb text often survives alongside real content, but the
    agent prompts already instruct hunting for specific facts (dates, file
    links) in whatever text they're given, so noise is tolerable."""
    html = _STRIP_BLOCKS_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_len]


def fetch_page_content(url: str, *, timeout: float = 15.0, max_len: int = 8000) -> str | None:
    """Best-effort live fetch + clean of *url*. Returns None on any failure
    (empty url, non-200, timeout, connection error, non-HTML content-type) —
    callers must treat this as optional, never block generation on it."""
    if not url:
        return None
    url = _resolve_url(url)
    try:
        response = httpx.get(
            url, timeout=timeout, follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        logger.warning("fetch failed for %s: %s", url, exc)
        return None

    if response.status_code != 200:
        logger.warning("fetch non-200 for %s: %s", url, response.status_code)
        return None

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        logger.warning("fetch non-HTML content-type for %s: %s", url, content_type)
        return None

    text = clean_html_to_text(response.text, max_len=max_len)
    return text or None
