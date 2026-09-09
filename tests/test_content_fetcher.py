"""Tests for enrichers.content_fetcher."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

from metadata_enricher.enrichers.content_fetcher import (
    _MIN_STATIC_TEXT_LEN,
    _fetch_via_obscura,
    _obscura_binary_path,
    _resolve_url,
    clean_html_to_text,
    fetch_page_content,
)


def _mock_response(
    status_code: int = 200, content_type: str = "text/html; charset=utf-8", text: str = ""
) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = {"content-type": content_type}
    response.text = text
    return response


class TestCleanHtmlToText:
    """Pure HTML->text cleaning logic."""

    def test_strips_script_and_style_blocks(self) -> None:
        html = "<html><head><style>.a{color:red}</style></head><body>Hello</body></html>"
        result = clean_html_to_text(html)
        assert "color" not in result
        assert "Hello" in result

    def test_strips_script_tag_contents(self) -> None:
        html = "<p>Keep me</p><script>var x = 1;</script><p>Also keep</p>"
        result = clean_html_to_text(html)
        assert "var x" not in result
        assert "Keep me" in result
        assert "Also keep" in result

    def test_strips_nav_header_footer(self) -> None:
        html = (
            "<nav>Site nav</nav><header>Site header</header>"
            "<main>Real content here</main>"
            "<footer>Site footer</footer>"
        )
        result = clean_html_to_text(html)
        assert "Site nav" not in result
        assert "Site header" not in result
        assert "Site footer" not in result
        assert "Real content here" in result

    def test_strips_remaining_tags(self) -> None:
        html = "<div><p>Paragraph <b>bold</b> text</p></div>"
        result = clean_html_to_text(html)
        assert "<" not in result
        assert "Paragraph" in result
        assert "bold" in result

    def test_collapses_whitespace(self) -> None:
        html = "<p>Line one</p>\n\n\n<p>   Line   two   </p>"
        result = clean_html_to_text(html)
        assert "  " not in result

    def test_truncates_to_max_len(self) -> None:
        html = "<p>" + ("word " * 5000) + "</p>"
        result = clean_html_to_text(html, max_len=100)
        assert len(result) == 100

    def test_unescapes_common_entities(self) -> None:
        html = "<p>Fish &amp; Chips&nbsp;shop</p>"
        result = clean_html_to_text(html)
        assert "&amp;" not in result
        assert "&nbsp;" not in result
        assert "Fish & Chips" in result

    def test_prefers_main_tag_over_surrounding_chrome(self) -> None:
        html = (
            "<header>Quienes Somos Buscador Contacto</header>"
            "<main>" + ("Real dataset description. " * 20) + "</main>"
            "<footer>Copyright 2024</footer>"
        )
        result = clean_html_to_text(html)
        assert "Real dataset description" in result
        assert "Quienes Somos" not in result
        assert "Copyright" not in result

    def test_prefers_article_tag_over_surrounding_chrome(self) -> None:
        html = (
            "<div class='navbar'>Menu Home Search Login</div>"
            "<article>" + ("Substantial article body text. " * 20) + "</article>"
            "<div class='sidebar'>Related links widget</div>"
        )
        result = clean_html_to_text(html)
        assert "Substantial article body" in result
        # Once <article> is substantial enough, it's used exclusively --
        # surrounding div chrome (not itself a skip tag) is excluded too.
        assert "Menu Home Search" not in result
        assert "Related links widget" not in result

    def test_falls_back_to_whole_page_when_no_main_tag_present(self) -> None:
        html = "<div><p>Some content</p><p>More content</p></div>"
        result = clean_html_to_text(html)
        assert "Some content" in result
        assert "More content" in result

    def test_falls_back_to_whole_page_when_main_tag_too_thin(self) -> None:
        html = "<main>Hi</main><div>" + ("Real body content here. " * 20) + "</div>"
        result = clean_html_to_text(html)
        # <main> content (2 chars) is below the substantiality threshold, so
        # the whole (chrome-stripped) page is used instead, including the div.
        assert "Real body content" in result

    def test_malformed_html_falls_back_without_raising(self) -> None:
        html = "<main><p>Unclosed paragraph<div>Nested badly</main>"
        result = clean_html_to_text(html)
        assert isinstance(result, str)

    def test_small_form_widget_is_dropped(self) -> None:
        """A short search/login form's own text stays discarded -- the
        original _SKIP_TAGS behavior, now gated on size instead of
        unconditional."""
        html = (
            "<form><input type='text'/><label>Search</label>"
            "<button>Go</button></form>"
            "<div>" + ("Real page content here. " * 20) + "</div>"
        )
        result = clean_html_to_text(html)
        assert "Search" not in result
        assert "Real page content" in result

    def test_substantial_form_content_is_kept(self) -> None:
        """A page-wide <form> wrapping the real article (e.g. an ASP.NET
        postback wrapper) must not be discarded just for being a <form> --
        regression test for the 2026-09-06 sample04/INE finding."""
        html = "<form>" + ("Real survey methodology text. " * 20) + "</form>"
        result = clean_html_to_text(html)
        assert "Real survey methodology text" in result

    def test_nav_inside_form_still_stripped(self) -> None:
        """A skip tag nested inside a kept <form> is still excluded --
        form-buffering must not bypass the ordinary skip-tag rules."""
        html = "<form><nav>Site nav junk</nav>" + ("Real form content. " * 20) + "</form>"
        result = clean_html_to_text(html)
        assert "Site nav junk" not in result
        assert "Real form content" in result

    def test_substantial_form_inside_main_counts_toward_main(self) -> None:
        """A kept form nested inside <main> must still be preferred over
        surrounding chrome, same as any other main-tag content."""
        html = (
            "<header>Site chrome text here</header>"
            "<main><form>" + ("Real form-wrapped article text. " * 20) + "</form></main>"
        )
        result = clean_html_to_text(html)
        assert "Real form-wrapped article text" in result
        assert "Site chrome text" not in result

    def test_main_inside_form_still_counts_toward_main(self) -> None:
        """Reverse nesting order from the test above: a <main> wrapped
        entirely inside a <form> (<form><main>...</main></form>) must still
        count toward main_chunks. Regression test: the close-time check
        used to sample self._main_depth only when </form> fired, which is
        always 0 in this ordering since </main> has already closed by
        then -- silently losing the form's text from main preference even
        though its size cleared the keep threshold."""
        html = (
            "<header>Site chrome text here</header>"
            "<form><main>" + ("Real main-in-form article text. " * 20) + "</main></form>"
        )
        result = clean_html_to_text(html)
        assert "Real main-in-form article text" in result
        assert "Site chrome text" not in result

    def test_unclosed_form_does_not_swallow_rest_of_document(self) -> None:
        """Malformed/truncated HTML with a <form> that never closes must
        not lose every bit of text after it to EOF. Regression test: before
        finalize()'s force-close, handle_data's unconditional
        "buffer into the open form" branch had no way to ever flush once
        the form never received its closing tag."""
        html = (
            "<form>" + ("Real unclosed form text. " * 20) + "<p>Trailing paragraph text here.</p>"
        )
        result = clean_html_to_text(html)
        assert "Real unclosed form text" in result
        assert "Trailing paragraph text here" in result


class TestResolveUrl:
    """Bare-DOI detection and doi.org resolution."""

    def test_bare_doi_resolves_through_doi_org(self) -> None:
        assert _resolve_url("10.5880/gfz.4.1.2020.012") == (
            "https://doi.org/10.5880/gfz.4.1.2020.012"
        )

    def test_normal_url_passes_through_unchanged(self) -> None:
        assert _resolve_url("https://example.com/dataset/1") == "https://example.com/dataset/1"

    def test_doi_url_with_scheme_passes_through_unchanged(self) -> None:
        # Already has a scheme -> not "bare" -> not double-resolved.
        url = "https://doi.org/10.5880/gfz.4.1.2020.012"
        assert _resolve_url(url) == url


class TestFetchPageContent:
    """fetch_page_content: best-effort, never raises, None on any failure."""

    def test_empty_url_returns_none_without_network_call(self) -> None:
        with patch("metadata_enricher.enrichers.content_fetcher.httpx.get") as mock_get:
            assert fetch_page_content("") is None
            mock_get.assert_not_called()

    def test_successful_fetch_returns_cleaned_text(self) -> None:
        response = _mock_response(text="<html><body><p>Hello world</p></body></html>")
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response
        ):
            result = fetch_page_content("https://example.com")
        assert result == "Hello world"

    def test_bare_doi_is_resolved_before_fetching(self) -> None:
        response = _mock_response(text="<p>Resolved content</p>")
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response
        ) as mock_get:
            result = fetch_page_content("10.5880/gfz.4.1.2020.012")
        assert result == "Resolved content"
        called_url = mock_get.call_args.args[0]
        assert called_url == "https://doi.org/10.5880/gfz.4.1.2020.012"

    def test_timeout_returns_none(self) -> None:
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            assert fetch_page_content("https://example.com") is None

    def test_connection_error_returns_none(self) -> None:
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            assert fetch_page_content("https://example.com") is None

    def test_non_200_returns_none(self) -> None:
        response = _mock_response(status_code=404)
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response
        ):
            assert fetch_page_content("https://example.com") is None

    def test_non_html_content_type_returns_none(self) -> None:
        response = _mock_response(content_type="application/pdf")
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response
        ):
            assert fetch_page_content("https://example.com") is None

    def test_plain_text_content_type_is_accepted(self) -> None:
        response = _mock_response(content_type="text/plain", text="Just plain text")
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response
        ):
            assert fetch_page_content("https://example.com") == "Just plain text"

    def test_empty_cleaned_text_returns_none(self) -> None:
        response = _mock_response(text="<script>only script content</script>")
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response
        ):
            assert fetch_page_content("https://example.com") is None

    def test_unexpected_exception_is_swallowed_not_raised(self) -> None:
        """Defense in depth: even a non-HTTPError exception must not propagate."""
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get",
            side_effect=RuntimeError("something unexpected"),
        ):
            assert fetch_page_content("https://example.com") is None

    def test_passes_timeout_and_max_len_through(self) -> None:
        response = _mock_response(text="<p>" + ("x" * 20) + "</p>")
        with patch(
            "metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response
        ) as mock_get:
            result = fetch_page_content("https://example.com", timeout=5.0, max_len=10)
        assert mock_get.call_args.kwargs["timeout"] == 5.0
        assert result is not None
        assert len(result) == 10


class TestObscuraBinaryPath:
    """Locating the optional obscura render binary."""

    def test_returns_none_when_not_found_anywhere(self) -> None:
        with patch("metadata_enricher.enrichers.content_fetcher.shutil.which", return_value=None):
            assert _obscura_binary_path() is None

    def test_finds_binary_on_path(self) -> None:
        with patch(
            "metadata_enricher.enrichers.content_fetcher.shutil.which",
            return_value="/usr/local/bin/obscura",
        ):
            assert _obscura_binary_path() == "/usr/local/bin/obscura"

    def test_finds_bundled_binary_when_frozen_and_staged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        bundled = tmp_path / "obscura"
        bundled.write_bytes(b"fake bundled binary")
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        with patch(
            "metadata_enricher.enrichers.content_fetcher.shutil.which",
            return_value=None,
        ):
            assert _obscura_binary_path() == str(bundled)

    def test_falls_back_to_path_when_frozen_but_staging_was_skipped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """visor.spec skips staging on an unsupported platform (see
        fetch_obscura.py) -- a frozen build must still fall through to a
        separately-installed PATH binary rather than crashing or refusing
        to look further."""
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        with patch(
            "metadata_enricher.enrichers.content_fetcher.shutil.which",
            return_value="/usr/local/bin/obscura",
        ):
            assert _obscura_binary_path() == "/usr/local/bin/obscura"


class TestFetchViaObscura:
    """_fetch_via_obscura: JS-render fallback, same never-raise contract."""

    def test_returns_none_when_binary_not_found(self) -> None:
        with patch(
            "metadata_enricher.enrichers.content_fetcher._obscura_binary_path", return_value=None
        ):
            assert _fetch_via_obscura("https://example.com", timeout=5.0, max_len=8000) is None

    def test_refuses_non_http_scheme_without_touching_subprocess(self) -> None:
        with patch("metadata_enricher.enrichers.content_fetcher.subprocess.run") as mock_run:
            assert _fetch_via_obscura("file:///etc/passwd", timeout=5.0, max_len=8000) is None
        mock_run.assert_not_called()

    def test_refuses_flag_like_or_schemeless_input(self) -> None:
        with patch("metadata_enricher.enrichers.content_fetcher.subprocess.run") as mock_run:
            assert _fetch_via_obscura("--dump", timeout=5.0, max_len=8000) is None
        mock_run.assert_not_called()

    def test_successful_render_is_cleaned_through_clean_html_to_text(self) -> None:
        completed = MagicMock(
            returncode=0,
            stdout=b"<html><body><main>Real rendered content here</main></body></html>",
            stderr=b"",
        )
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher._obscura_binary_path",
                return_value="/usr/local/bin/obscura",
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher.subprocess.run",
                return_value=completed,
            ) as mock_run,
        ):
            result = _fetch_via_obscura("https://example.com", timeout=5.0, max_len=8000)
        assert result == "Real rendered content here"
        called_args = mock_run.call_args.args[0]
        assert called_args == [
            "/usr/local/bin/obscura",
            "fetch",
            "https://example.com",
            "--dump",
            "html",
            "--timeout",
            "5",
        ]

    def test_sub_one_second_timeout_floors_to_one(self) -> None:
        """str(int(0.5)) == '0' would pass obscura a nonsensical --timeout 0
        -- floor to at least 1. The subprocess.run(timeout=...) bound stays
        the caller's real value + slack regardless, so this only affects
        what obscura itself is told."""
        completed = MagicMock(returncode=0, stdout=b"<main>content</main>", stderr=b"")
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher._obscura_binary_path",
                return_value="/usr/local/bin/obscura",
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher.subprocess.run",
                return_value=completed,
            ) as mock_run,
        ):
            _fetch_via_obscura("https://example.com", timeout=0.5, max_len=8000)
        assert mock_run.call_args.args[0][-1] == "1"

    def test_non_zero_exit_returns_none(self) -> None:
        completed = MagicMock(returncode=1, stdout=b"", stderr=b"navigation failed")
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher._obscura_binary_path",
                return_value="/usr/local/bin/obscura",
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher.subprocess.run",
                return_value=completed,
            ),
        ):
            assert _fetch_via_obscura("https://example.com", timeout=5.0, max_len=8000) is None

    def test_timeout_returns_none(self) -> None:
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher._obscura_binary_path",
                return_value="/usr/local/bin/obscura",
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="obscura", timeout=5.0),
            ),
        ):
            assert _fetch_via_obscura("https://example.com", timeout=5.0, max_len=8000) is None

    def test_binary_not_executable_returns_none(self) -> None:
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher._obscura_binary_path",
                return_value="/usr/local/bin/obscura",
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher.subprocess.run",
                side_effect=OSError("permission denied"),
            ),
        ):
            assert _fetch_via_obscura("https://example.com", timeout=5.0, max_len=8000) is None

    def test_empty_stdout_returns_none(self) -> None:
        completed = MagicMock(returncode=0, stdout=b"   ", stderr=b"")
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher._obscura_binary_path",
                return_value="/usr/local/bin/obscura",
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher.subprocess.run",
                return_value=completed,
            ),
        ):
            assert _fetch_via_obscura("https://example.com", timeout=5.0, max_len=8000) is None


class TestFetchPageContentJsRenderFallback:
    """fetch_page_content's opt-in JS-render retry path."""

    def test_disabled_by_default_thin_result_not_retried(self) -> None:
        response = _mock_response(text="<p>Hi</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura"
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com")
        mock_render.assert_not_called()
        assert result == "Hi"

    def test_thin_result_triggers_render_when_enabled(self) -> None:
        response = _mock_response(text="<p>Hi</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura",
                return_value="Real rendered content. " * 20,
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_called_once()
        assert result is not None
        assert "Real rendered content" in result

    def test_substantial_static_result_is_not_retried(self) -> None:
        substantial = "Real static page content. " * 20
        response = _mock_response(text=f"<p>{substantial}</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura"
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_not_called()
        assert result is not None
        assert "Real static page content" in result

    def test_render_failure_falls_back_to_thin_static_text(self) -> None:
        response = _mock_response(text="<p>Hi</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura",
                return_value=None,
            ),
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        assert result == "Hi"

    def test_timeout_triggers_render_when_enabled(self) -> None:
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher.httpx.get",
                side_effect=httpx.TimeoutException("timed out"),
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura",
                return_value="Real rendered content. " * 20,
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_called_once()
        assert result is not None

    def test_non_200_is_not_retried_even_when_enabled(self) -> None:
        response = _mock_response(status_code=404)
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura"
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_not_called()
        assert result is None

    def test_non_html_content_type_is_not_retried_even_when_enabled(self) -> None:
        response = _mock_response(content_type="application/pdf")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura"
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_not_called()
        assert result is None

    def test_connection_error_is_not_retried_even_when_enabled(self) -> None:
        """Distinct from timeout: obscura would hit the exact same
        unreachable host, so a connection error is trusted as-is rather
        than wasting a render attempt on it."""
        with (
            patch(
                "metadata_enricher.enrichers.content_fetcher.httpx.get",
                side_effect=httpx.ConnectError("connection refused"),
            ),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura"
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_not_called()
        assert result is None

    def test_exactly_at_threshold_is_not_retried(self) -> None:
        exact = "x" * _MIN_STATIC_TEXT_LEN
        response = _mock_response(text=f"<p>{exact}</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura"
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_not_called()
        assert result == exact

    def test_one_char_below_threshold_is_retried(self) -> None:
        thin = "x" * (_MIN_STATIC_TEXT_LEN - 1)
        response = _mock_response(text=f"<p>{thin}</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura",
                return_value="y" * (_MIN_STATIC_TEXT_LEN + 50),
            ) as mock_render,
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        mock_render.assert_called_once()
        assert result == "y" * (_MIN_STATIC_TEXT_LEN + 50)

    def test_render_result_shorter_than_static_keeps_static(self) -> None:
        static = "x" * 50  # thin (below threshold) but real
        response = _mock_response(text=f"<p>{static}</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura",
                return_value="y" * 5,
            ),
        ):
            result = fetch_page_content("https://example.com", js_render_fallback=True)
        assert result == static

    def test_bare_doi_is_resolved_before_being_passed_to_render(self) -> None:
        response = _mock_response(text="<p>Hi</p>")
        with (
            patch("metadata_enricher.enrichers.content_fetcher.httpx.get", return_value=response),
            patch(
                "metadata_enricher.enrichers.content_fetcher._fetch_via_obscura",
                return_value="Real rendered content. " * 20,
            ) as mock_render,
        ):
            fetch_page_content("10.5880/gfz.4.1.2020.012", js_render_fallback=True)
        mock_render.assert_called_once()
        assert mock_render.call_args.args[0] == "https://doi.org/10.5880/gfz.4.1.2020.012"
