"""Tests for country_extractor.py — CountryExtractor class."""

from __future__ import annotations

import pytest

from metadata_enricher.enrichers.country_extractor import (
    CountryExtractor,
    _extract_country_from_locale,
    _extract_country_from_region,
)


_HTML_OG_LOCALE = """\
<html>
<head>
<meta property="og:locale" content="es_CL">
</head>
<body></body>
</html>"""

_HTML_GEO_COUNTRY = """\
<html>
<head>
<meta name="geo.country" content="CL">
</head>
<body></body>
</html>"""

_HTML_GEO_REGION = """\
<html>
<head>
<meta name="geo.region" content="CL-RM">
</head>
<body></body>
</html>"""

_HTML_LANG = """\
<html lang="es-CL">
<head></head>
<body></body>
</html>"""

_HTML_OG_LOCALE_AND_GEO_COUNTRY = """\
<html>
<head>
<meta property="og:locale" content="es_CL">
<meta name="geo.country" content="AR">
</head>
<body></body>
</html>"""

_HTML_NO_MATCH = """\
<html>
<head>
<meta name="description" content="A dataset">
</head>
<body><p>Hello</p></body>
</html>"""

_HTML_SWAPPED_ATTRS = """\
<html>
<head>
<meta content="es_CL" property="og:locale">
</head>
<body></body>
</html>"""


@pytest.fixture
def extractor() -> CountryExtractor:
    return CountryExtractor()


class TestExtractCountryFromLocale:
    @pytest.mark.parametrize(
        "locale,expected",
        [
            pytest.param("es_CL", "CL", id="standard_locale"),
            pytest.param("pt_BR", "BR", id="locale_with_region"),
            pytest.param("esCL", None, id="no_underscore"),
            pytest.param("es_CHL", None, id="invalid_country_code_length"),
            pytest.param("es_cl", "CL", id="lowercase_country"),
        ],
    )
    def test_extract_country_from_locale(self, locale: str, expected: str | None) -> None:
        assert _extract_country_from_locale(locale) == expected


class TestExtractCountryFromRegion:
    @pytest.mark.parametrize(
        "region,expected",
        [
            pytest.param("CL-RM", "CL", id="standard_region"),
            pytest.param("CLRM", None, id="no_hyphen_returns_none"),
            pytest.param("CHL-RM", None, id="invalid_prefix_length"),
        ],
    )
    def test_extract_country_from_region(self, region: str, expected: str | None) -> None:
        assert _extract_country_from_region(region) == expected


class TestExtractFromHtml:
    @pytest.mark.parametrize(
        "html,expected",
        [
            pytest.param(_HTML_OG_LOCALE, "CL", id="og_locale_priority"),
            pytest.param(_HTML_GEO_COUNTRY, "CL", id="geo_country"),
            pytest.param(_HTML_GEO_REGION, "CL", id="geo_region"),
            pytest.param(_HTML_LANG, "CL", id="html_lang_fallback"),
            pytest.param(_HTML_NO_MATCH, None, id="no_match_returns_none"),
            pytest.param("", None, id="empty_html"),
            pytest.param(_HTML_OG_LOCALE_AND_GEO_COUNTRY, "CL", id="og_locale_over_geo_country"),
            pytest.param(_HTML_SWAPPED_ATTRS, "CL", id="swapped_attribute_order"),
        ],
    )
    def test_extract_from_html(
        self, extractor: CountryExtractor, html: str, expected: str | None
    ) -> None:
        assert extractor.extract_from_html(html) == expected


class TestExtractFromUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            pytest.param("https://datos.gob.cl/dataset", "CL", id="cl_tld"),
            pytest.param("https://www.gov.br/", "BR", id="br_tld"),
            pytest.param("https://data.gov.uk/", "GB", id="uk_tld_maps_to_gb"),
            pytest.param("https://datos.gob.es/", "ES", id="es_tld"),
            pytest.param("https://example.jp", "JP", id="jp_tld"),
            pytest.param("https://example.fr", "FR", id="fr_tld"),
            pytest.param("https://example.de", "DE", id="de_tld"),
            pytest.param("https://example.it", "IT", id="it_tld"),
            pytest.param("https://example.pt", "PT", id="pt_tld"),
            pytest.param("https://example.uy", "UY", id="uy_tld"),
            pytest.param("https://example.bo", "BO", id="bo_tld"),
            pytest.param("https://example.ec", "EC", id="ec_tld"),
            pytest.param("https://example.ve", "VE", id="ve_tld"),
            pytest.param("https://example.py", "PY", id="py_tld"),
            pytest.param("https://example.au", "AU", id="au_tld"),
            pytest.param("https://example.cn", "CN", id="cn_tld"),
            pytest.param("https://example.ca", "CA", id="ca_tld"),
            pytest.param("https://www.rasgos.cl.com/", None, id="com_tld_is_generic"),
            pytest.param("https://example.org", None, id="org_tld_is_generic"),
            pytest.param("https://example.io", None, id="io_tld_is_generic"),
            pytest.param("https://example.com", None, id="com_tld"),
            pytest.param("", None, id="empty_url"),
            pytest.param("not-a-url", None, id="no_hostname"),
        ],
    )
    def test_extract_from_url(
        self, extractor: CountryExtractor, url: str, expected: str | None
    ) -> None:
        assert extractor.extract_from_url(url) == expected


class TestExtractCountry:
    @pytest.mark.parametrize(
        "html_content,url,expected",
        [
            pytest.param(_HTML_GEO_COUNTRY, "https://example.br", "CL", id="html_priority_over_url"),
            pytest.param(_HTML_NO_MATCH, "https://example.cl", "CL", id="url_fallback_when_html_none"),
            pytest.param(_HTML_GEO_COUNTRY, None, "CL", id="html_only"),
            pytest.param(None, "https://example.cl", "CL", id="url_only"),
            pytest.param(None, None, None, id="both_none"),
            pytest.param("", "https://example.cl", "CL", id="html_empty_string_falls_back_to_url"),
            pytest.param(None, "https://www.rasgos.cl/", "CL", id="rasgos_cl_url"),
            pytest.param(
                None,
                "https://datos.gob.cl/dataset/gastos-municipales",
                "CL",
                id="datos_gob_cl_url",
            ),
        ],
    )
    def test_extract_country(
        self,
        extractor: CountryExtractor,
        html_content: str | None,
        url: str | None,
        expected: str | None,
    ) -> None:
        assert extractor.extract_country(html_content=html_content, url=url) == expected
