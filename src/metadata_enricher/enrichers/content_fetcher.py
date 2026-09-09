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

A second, independently opt-in layer (``PipelineConfig.enable_js_render_
fallback``) retries a too-thin/failed static fetch through a real JS engine
(the ``obscura`` CLI, https://github.com/h4ckf0r0day/obscura) before giving
up -- for the real, measured case of a JS-rendered SPA whose static HTML
carries none of the page's actual content. Same fail-soft contract: a
missing binary, timeout, or render failure just falls back to whatever the
static fetch already returned. See docs/cdif_pivot_implementation_plan.md's
"JS-render fallback" phase for the evaluation this was built from.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_STRIP_BLOCKS_RE = re.compile(r"(?is)<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_BARE_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

# Below this length, a *successful* static fetch is treated as too thin to
# trust -- typically a JS-rendered SPA shell whose real content never made it
# into the static HTML at all (confirmed live against real golden-fixture
# URLs: dead pages measured 9/23/72/123 chars vs. a real page's thousands).
# Only load-bearing when the caller opts into js_render_fallback -- see
# _fetch_via_obscura below.
_MIN_STATIC_TEXT_LEN = 200
_OBSCURA_BINARY_NAME = "obscura.exe" if sys.platform == "win32" else "obscura"
# Slack added on top of the caller's own timeout for the *subprocess* bound,
# since obscura's own --timeout only bounds page navigation, not process
# startup/V8 init -- see fetch_page_content's docstring.
_OBSCURA_TIMEOUT_SLACK = 5.0

# Chrome tags whose text is never real content, wherever they appear in the
# tree (unlike _STRIP_BLOCKS_RE above, this is nesting-aware via HTMLParser,
# so it also catches e.g. a <nav> inside a <main>).
_SKIP_TAGS = frozenset(
    {"script", "style", "nav", "header", "footer", "noscript", "aside", "svg", "button", "select"}
)
# <form> is handled separately from _SKIP_TAGS, not unconditionally skipped:
# a small search/login widget's form has little text and should be dropped,
# but some real pages (confirmed live: an ASP.NET/Sitefinity-built .gov.cl
# survey page) wrap nearly the entire article in one page-wide <form
# method="post" id="aspnetForm">, and unconditionally skipping it discarded
# 82.6% of that page's real content. Buffered per open <form> (see
# _MainContentParser._form_stack) and only kept if its own text clears
# _MIN_KEPT_FORM_TEXT_LEN once it closes -- same "too thin, discard"
# philosophy as _MIN_MAIN_TEXT_LEN below, just inverted (small form -> drop,
# substantial form -> keep).
_FORM_TAG = "form"
_MIN_KEPT_FORM_TEXT_LEN = 200
# Semantic containers real page content usually lives in on sites that use
# them -- preferred over the whole page when present and substantial, since
# whole-page text otherwise mixes in nav/breadcrumb/sidebar prose that isn't
# wrapped in one of _SKIP_TAGS (e.g. a <div class="navbar">).
_MAIN_TAGS = frozenset({"main", "article"})
# Below this length a <main>/<article> extraction is treated as too thin to
# trust (e.g. an empty shell with just a heading) -- falls back to whole-page.
_MIN_MAIN_TEXT_LEN = 200

USER_AGENT = "Mozilla/5.0 (compatible; gema/1.0)"


class _MainContentParser(HTMLParser):
    """Nesting-aware HTML text extractor: skips real chrome tags anywhere in
    the tree, and separately collects text inside <main>/<article> so callers
    can prefer it over the whole page when it looks substantial."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._main_depth = 0
        # One buffer list per currently-open <form>, innermost last. Text
        # inside any open form accumulates here instead of all_chunks/
        # main_chunks directly -- only flushed (or dropped) when its form
        # closes, see handle_endtag. Paired 1:1 with _form_saw_main_stack.
        self._form_stack: list[list[str]] = []
        # Parallel stack: whether *any* text buffered into the matching
        # _form_stack entry was seen while a <main>/<article> was open --
        # decided at close time instead of sampling self._main_depth then,
        # since a <form> can wrap a <main> entirely (<form><main>...</main>
        # </form>): by the time </form> fires, </main> has already closed
        # and _main_depth is back to 0, so a close-time sample would miss
        # it. Set True eagerly on push too, for the (already-covered)
        # reverse nesting (<main><form>...) where the form opens inside an
        # already-open main.
        self._form_saw_main_stack: list[bool] = []
        self.all_chunks: list[str] = []
        self.main_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == _FORM_TAG:
            self._form_stack.append([])
            self._form_saw_main_stack.append(self._main_depth > 0)
        elif tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _MAIN_TAGS:
            self._main_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        pass  # self-closing tags (e.g. <br/>) never carry text of their own.

    def handle_endtag(self, tag: str) -> None:
        if tag == _FORM_TAG and self._form_stack:
            form_text = "".join(self._form_stack.pop())
            saw_main = self._form_saw_main_stack.pop()
            if len(form_text.strip()) < _MIN_KEPT_FORM_TEXT_LEN:
                return  # too thin to trust as real content -- drop, like a login/search widget
            if self._form_stack:
                self._form_stack[-1].append(form_text)  # nested form: bubble up, decide at outer close
                if saw_main:
                    self._form_saw_main_stack[-1] = True  # bubble the flag up too
                return
            self.all_chunks.append(form_text)
            if saw_main:
                self.main_chunks.append(form_text)
        elif tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _MAIN_TAGS and self._main_depth > 0:
            self._main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._form_stack:
            self._form_stack[-1].append(data)
            if self._main_depth > 0:
                self._form_saw_main_stack[-1] = True
            return
        self.all_chunks.append(data)
        if self._main_depth > 0:
            self.main_chunks.append(data)

    def finalize(self) -> None:
        """Force-close any <form>s still open at end-of-document.

        Malformed/truncated HTML (a real possibility on live-fetched pages)
        can leave a <form> unclosed; without this, handle_data's
        unconditional "buffer into the open form" branch would silently
        swallow every bit of text from the unclosed <form> through EOF into
        a buffer nothing ever flushes. Reuses handle_endtag's own keep/drop/
        bubble logic by treating end-of-document as an implicit close, same
        as a browser's forgiving HTML parser would."""
        while self._form_stack:
            self.handle_endtag(_FORM_TAG)


def _extract_relevant_text(html: str) -> str:
    """Parse *html*, preferring <main>/<article> text over the whole page
    when present and substantial. Falls back to the whole (chrome-stripped)
    page on any parse error or when no substantial main content is found --
    same tolerance contract as the rest of this module (never raises)."""
    parser = _MainContentParser()
    try:
        parser.feed(html)
        parser.finalize()
    except Exception as exc:  # malformed markup must never break extraction
        logger.debug("HTML parse failed, falling back to regex strip: %s", exc)
        return _STRIP_BLOCKS_RE.sub(" ", html)

    main_text = "".join(parser.main_chunks)
    if len(main_text.strip()) >= _MIN_MAIN_TEXT_LEN:
        return main_text
    return "".join(parser.all_chunks)


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
    """Extract page text (preferring <main>/<article> when substantial, see
    _extract_relevant_text), strip any remaining tags, collapse whitespace,
    truncate to *max_len*.

    Not a full readability algorithm — a <main>/<article>-less page's real
    content can still carry alongside nav/breadcrumb text not wrapped in any
    of _SKIP_TAGS, but the agent prompts already instruct hunting for
    specific facts (dates, file links) in whatever text they're given, so
    residual noise is tolerable.
    """
    text = _extract_relevant_text(html)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_len]


def _obscura_binary_path() -> str | None:
    """Locate the ``obscura`` headless-render binary.

    A frozen Visor build ships it bundled next to the app (staged into
    PyInstaller's ``binaries`` by visor.spec, landing in ``sys._MEIPASS`` at
    runtime — see that spec file's own comments for the vendoring step).
    Outside a frozen build (plain CLI/library use), it must be a separately
    installed prerequisite on ``PATH`` — gema never downloads it itself.
    Returns ``None`` if it can't be found either way, which callers treat as
    "render fallback unavailable", not an error.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / _OBSCURA_BINARY_NAME
        if bundled.is_file():
            return str(bundled)
    return shutil.which(_OBSCURA_BINARY_NAME)


def _fetch_via_obscura(url: str, *, timeout: float, max_len: int) -> str | None:
    """Render *url* with a real JS engine (via the ``obscura`` CLI) and clean
    the resulting DOM through the same ``clean_html_to_text`` path as a plain
    static fetch — one extraction implementation, not two (verified live:
    obscura's rendered ``--dump html`` output carries real <main>/<article>
    tags on real pages, so the existing extractor behaves the same on it as
    on server-rendered HTML).

    Never raises: a missing binary, non-zero exit, or timeout all degrade to
    ``None`` plus a logged warning, identical in spirit to fetch_page_
    content's own contract.
    """
    if not url.startswith(("http://", "https://")):
        # Defense in depth: the only caller (fetch_page_content) never
        # reaches here with anything else -- a non-http(s) string fails at
        # httpx.get() before render_eligible is ever set -- but this
        # function shells out to an external binary, so refuse explicitly
        # rather than relying on that call-site guarantee.
        logger.warning("refusing to render non-http(s) url via obscura: %s", url)
        return None
    binary = _obscura_binary_path()
    if binary is None:
        logger.warning("obscura binary not found -- skipping JS-render fallback for %s", url)
        return None
    try:
        result = subprocess.run(
            [binary, "fetch", url, "--dump", "html", "--timeout", str(max(1, int(timeout)))],
            capture_output=True,
            timeout=timeout + _OBSCURA_TIMEOUT_SLACK,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("obscura render timed out for %s", url)
        return None
    except OSError as exc:  # binary present but not executable, etc.
        logger.warning("obscura render failed to start for %s: %s", url, exc)
        return None

    if result.returncode != 0:
        logger.warning(
            "obscura render non-zero exit for %s: %s",
            url,
            result.stderr.decode("utf-8", errors="replace")[:200],
        )
        return None

    html = result.stdout.decode("utf-8", errors="replace")
    if not html.strip():
        return None
    return clean_html_to_text(html, max_len=max_len) or None


def fetch_page_content(
    url: str,
    *,
    timeout: float = 15.0,
    max_len: int = 8000,
    js_render_fallback: bool = False,
) -> str | None:
    """Best-effort live fetch + clean of *url*.

    Returns ``None`` on any failure (empty url, non-200, timeout, connection
    error, non-HTML/text content-type) — callers must treat this as purely
    optional and never let it block resource processing.

    When *js_render_fallback* is True, a static fetch that either times out
    (a slow-but-reachable page that might just need more time/a browser) or
    succeeds but comes back too thin to trust (under _MIN_STATIC_TEXT_LEN,
    the JS-rendered-SPA case) is retried via _fetch_via_obscura. A real
    non-200, a non-HTML content-type, a connection error, or any other
    request failure is *not* retried: obscura hits the exact same network
    path a connection error already failed on, so rendering would just
    waste a subprocess timeout on an unreachable host, and rendering a 404
    or a PDF doesn't make it a webpage either way.
    """
    if not url:
        return None
    resolved_url = _resolve_url(url)

    static_text: str | None = None
    render_eligible = False
    try:
        response = httpx.get(
            resolved_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.TimeoutException as exc:
        logger.warning("fetch timed out for %s: %s", resolved_url, exc)
        render_eligible = True
    except httpx.HTTPError as exc:
        logger.warning("fetch failed for %s: %s", resolved_url, exc)
    except Exception as exc:  # defensive: never let a fetch failure propagate
        logger.warning("fetch failed for %s: %s", resolved_url, exc)
    else:
        if response.status_code != 200:
            logger.warning("fetch non-200 for %s: %s", resolved_url, response.status_code)
        else:
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                logger.warning(
                    "fetch non-HTML content-type for %s: %s", resolved_url, content_type
                )
            else:
                static_text = clean_html_to_text(response.text, max_len=max_len) or None
                if static_text is None or len(static_text) < _MIN_STATIC_TEXT_LEN:
                    render_eligible = True

    if not js_render_fallback or not render_eligible:
        return static_text

    rendered_text = _fetch_via_obscura(resolved_url, timeout=timeout, max_len=max_len)
    if rendered_text and (static_text is None or len(rendered_text) > len(static_text)):
        return rendered_text
    return static_text
