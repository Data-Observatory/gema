"""The rate limit keys on Caddy's {client_ip}; Caddy must trust X-Forwarded-For only from
the docker network gateway (the hop every loopback connection, Funnel included, comes
through), never from all private ranges (any LAN client could then spoof its address)."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

DEMO = Path(__file__).resolve().parents[2]


def test_caddy_trusts_only_the_compose_network_gateway() -> None:
    caddyfile = (DEMO / "Caddyfile").read_text(encoding="utf-8")
    compose = (DEMO / "compose.yml").read_text(encoding="utf-8")

    trusted = re.findall(r"^\s*trusted_proxies\s+static\s+(.+)$", caddyfile, re.MULTILINE)
    assert len(trusted) == 1, trusted
    ranges = trusted[0].split()
    assert "private_ranges" not in ranges

    subnet = re.search(r"subnet:\s*([0-9./]+)", compose)
    assert subnet, "compose.yml must pin the dataverse network subnet"
    gateway = next(ipaddress.ip_network(subnet.group(1)).hosts())  # docker's default gateway
    assert ranges == [f"{gateway}/32"]
    assert re.search(r"^\s*trusted_proxies_strict\s*$", caddyfile, re.MULTILINE)
