"""SSRF guard tests (OWASP API7)."""

from __future__ import annotations

import pytest

from app.core.ssrf_guard import (
    SSRFBlocked,
    _ip_is_blocked,
    _resolve_and_check,
    safe_async_client,
)


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "192.168.255.255",
        "127.0.0.1",
        "127.255.255.255",
        "169.254.169.254",  # AWS/GCP metadata
        "169.254.1.1",  # link-local
        "::1",
        "fc00::1",  # ULA
        "fe80::1",  # link-local v6
    ],
)
def test_blocks_private_addresses(ip):
    assert _ip_is_blocked(ip) is True


@pytest.mark.parametrize(
    "ip",
    [
        "8.8.8.8",
        "1.1.1.1",
        "151.101.0.1",  # Fastly public
        "2606:4700:4700::1111",  # Cloudflare public v6
    ],
)
def test_allows_public_addresses(ip):
    assert _ip_is_blocked(ip) is False


def test_resolve_blocks_localhost():
    with pytest.raises(SSRFBlocked, match="private_ip"):
        _resolve_and_check("localhost")


def test_safe_async_client_is_context_manager():
    client = safe_async_client()
    assert client is not None
