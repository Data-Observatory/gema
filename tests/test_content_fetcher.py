"""Tests for enrichers.content_fetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from metadata_enricher.enrichers.content_fetcher import (
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
