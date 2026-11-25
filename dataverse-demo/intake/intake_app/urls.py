"""URL validation and normalization for submitted resources."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LEN = 2000
_DEFAULT_PORTS = {"http": 80, "https": 443}
_BAD_CHARS_RE = re.compile(r"[\s\x00-\x1f\x7f]")
_INTERNAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")


class InvalidUrlError(ValueError):
    """The submitted URL is not acceptable. ``str(exc)`` is safe to show to the user."""


def normalize_url(raw: str) -> str:
    """Canonical form used for duplicate detection.

    Lowercases scheme and host, drops the fragment, default ports and a trailing slash
    (``https://A.org/x/#top`` -> ``https://a.org/x``). The query string is kept: two
    different queries are two different resources. Raises ``InvalidUrlError``.
    """
    raw = (raw or "").strip()
    if not raw:
        raise InvalidUrlError("URL is required.")
    if len(raw) > MAX_URL_LEN:
        raise InvalidUrlError(f"URL is too long (max {MAX_URL_LEN} characters).")
    if _BAD_CHARS_RE.search(raw):
        raise InvalidUrlError("URL must not contain spaces or control characters.")
    try:
        parts = urlsplit(raw)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise InvalidUrlError("That does not look like a valid URL.") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidUrlError("URL must start with http:// or https://")
    if not host:
        raise InvalidUrlError("URL has no host name.")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError("URLs with embedded credentials are not accepted.")
    host = host.rstrip(".").lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def _addr_is_public(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr.split("%")[0]).is_global
    except ValueError:
        return False


def is_forbidden_literal(url_norm: str) -> bool:
    """Cheap, DNS-free SSRF guard applied at submit time: IP literals that are not public,
    ``localhost`` and single-label / ``.local`` style names. (The full DNS-resolving check
    runs again right before the server fetches the URL, see ``host_resolves_public``.)"""
    host = (urlsplit(url_norm).hostname or "").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(_INTERNAL_SUFFIXES)
    return not _addr_is_public(host)


def host_resolves_public(host: str) -> bool:
    """True if every address *host* resolves to is globally routable. Raises ``OSError`` on
    DNS failure (the caller decides whether that is transient)."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return all(_addr_is_public(str(info[4][0])) for info in infos)
