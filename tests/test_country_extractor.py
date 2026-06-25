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
    def test_standard_locale(self) -> None:
        assert _extract_country_from_locale("es_CL") == "CL"

    def test_locale_with_region(self) -> None:
        assert _extract_country_from_locale("pt_BR") == "BR"

    def test_no_underscore(self) -> None:
        assert _extract_country_from_locale("esCL") is None

    def test_invalid_country_code_length(self) -> None:
        assert _extract_country_from_locale("es_CHL") is None

    def test_lowercase_country(self) -> None:
        assert _extract_country_from_locale("es_cl") == "CL"


class TestExtractCountryFromRegion:
    def test_standard_region(self) -> None:
        assert _extract_country_from_region("CL-RM") == "CL"

    def test_no_hyphen_returns_none(self) -> None:
        assert _extract_country_from_region("CLRM") is None

    def test_invalid_prefix_length(self) -> None:
        assert _extract_country_from_region("CHL-RM") is None


class TestExtractFromHtml:
    def test_og_locale_priority(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html(_HTML_OG_LOCALE) == "CL"

    def test_geo_country(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html(_HTML_GEO_COUNTRY) == "CL"

    def test_geo_region(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html(_HTML_GEO_REGION) == "CL"

    def test_html_lang_fallback(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html(_HTML_LANG) == "CL"

    def test_no_match_returns_none(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html(_HTML_NO_MATCH) is None

    def test_empty_html(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html("") is None

    def test_og_locale_over_geo_country(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html(_HTML_OG_LOCALE_AND_GEO_COUNTRY) == "CL"

    def test_swapped_attribute_order(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_html(_HTML_SWAPPED_ATTRS) == "CL"


class TestExtractFromUrl:
    def test_cl_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://datos.gob.cl/dataset") == "CL"

    def test_br_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://www.gov.br/") == "BR"

    def test_uk_tld_maps_to_gb(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://data.gov.uk/") == "GB"

    def test_es_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://datos.gob.es/") == "ES"

    def test_com_tld_is_generic(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://www.rasgos.cl.com/") is None

    def test_org_tld_is_generic(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.org") is None

    def test_io_tld_is_generic(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.io") is None

    def test_empty_url(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("") is None

    def test_no_hostname(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("not-a-url") is None

    def test_jp_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.jp") == "JP"

    def test_com_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.com") is None

    def test_fr_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.fr") == "FR"

    def test_de_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.de") == "DE"

    def test_it_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.it") == "IT"

    def test_pt_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.pt") == "PT"

    def test_uy_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.uy") == "UY"

    def test_bo_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.bo") == "BO"

    def test_ec_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.ec") == "EC"

    def test_ve_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.ve") == "VE"

    def test_py_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.py") == "PY"

    def test_au_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.au") == "AU"

    def test_cn_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.cn") == "CN"

    def test_ca_tld(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_from_url("https://example.ca") == "CA"


class TestExtractCountry:
    def test_html_priority_over_url(self, extractor: CountryExtractor) -> None:
        result = extractor.extract_country(
            html_content=_HTML_GEO_COUNTRY,
            url="https://example.br",
        )
        assert result == "CL"

    def test_url_fallback_when_html_none(self, extractor: CountryExtractor) -> None:
        result = extractor.extract_country(
            html_content=_HTML_NO_MATCH,
            url="https://example.cl",
        )
        assert result == "CL"

    def test_html_only(self, extractor: CountryExtractor) -> None:
        result = extractor.extract_country(html_content=_HTML_GEO_COUNTRY)
        assert result == "CL"

    def test_url_only(self, extractor: CountryExtractor) -> None:
        result = extractor.extract_country(url="https://example.cl")
        assert result == "CL"

    def test_both_none(self, extractor: CountryExtractor) -> None:
        assert extractor.extract_country() is None

    def test_html_empty_string_falls_back_to_url(self, extractor: CountryExtractor) -> None:
        result = extractor.extract_country(
            html_content="",
            url="https://example.cl",
        )
        assert result == "CL"

    def test_rasgos_cl_url(self, extractor: CountryExtractor) -> None:
        result = extractor.extract_country(url="https://www.rasgos.cl/")
        assert result == "CL"

    def test_datos_gob_cl_url(self, extractor: CountryExtractor) -> None:
        result = extractor.extract_country(url="https://datos.gob.cl/dataset/gastos-municipales")
        assert result == "CL"
