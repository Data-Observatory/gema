from __future__ import annotations

import pytest
from intake_app.urls import InvalidUrlError, is_forbidden_literal, normalize_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.ORG/Path/", "https://example.org/Path"),
        ("https://example.org", "https://example.org"),
        ("https://example.org/", "https://example.org"),
        ("https://example.org/a/b/#section", "https://example.org/a/b"),
        ("  https://example.org/x  ", "https://example.org/x"),
        ("HTTPS://EXAMPLE.org:443/x", "https://example.org/x"),
        ("http://example.org:80/x/", "http://example.org/x"),
        ("http://example.org:8080/x", "http://example.org:8080/x"),
        ("https://example.org./x", "https://example.org/x"),
        ("https://example.org/x?a=1&b=2#f", "https://example.org/x?a=1&b=2"),
        ("https://example.org/x/?a=1", "https://example.org/x?a=1"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_equivalent_spellings_collapse_to_one_key() -> None:
    variants = [
        "https://Data.Example.org/set/1",
        "https://data.example.org/set/1/",
        "https://data.example.org/set/1#top",
        "HTTPS://DATA.EXAMPLE.ORG:443/set/1/",
    ]
    assert len({normalize_url(v) for v in variants}) == 1


def test_http_and_https_and_queries_stay_distinct() -> None:
    assert normalize_url("http://a.org/x") != normalize_url("https://a.org/x")
    assert normalize_url("https://a.org/x?id=1") != normalize_url("https://a.org/x?id=2")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "example.org/x",
        "ftp://example.org/x",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://",
        "https:///x",
        "https://exa mple.org",
        "https://user:pw@example.org/",
        "https://example.org:99999/",
        "https://example.org/\x00",
        "https://example.org/" + "a" * 2100,
    ],
)
def test_invalid_urls_rejected(raw: str) -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url(raw)


@pytest.mark.parametrize(
    ("url", "forbidden"),
    [
        ("https://example.org/x", False),
        ("https://8.8.8.8/x", False),
        ("http://localhost:8080/api", True),
        ("http://127.0.0.1/", True),
        ("http://10.213.77.5:8080/", True),
        ("http://192.168.1.10/", True),
        ("http://169.254.169.254/latest/meta-data", True),
        ("http://[::1]/", True),
        ("http://dataverse:8080/", True),
        ("http://printer.local/", True),
    ],
)
def test_forbidden_literal_hosts(url: str, forbidden: bool) -> None:
    assert is_forbidden_literal(normalize_url(url)) is forbidden
