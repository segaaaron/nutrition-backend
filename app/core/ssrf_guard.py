"""SSRF guard for outbound HTTP requests (OWASP API7).

Blocks requests to RFC1918 private ranges, link-local, loopback, cloud metadata
IPs (AWS/GCP/Azure: 169.254.169.254, fd00:ec2::254), and broadcast/multicast.
Provides `safe_async_client()` factory that wraps `httpx.AsyncClient` with a
custom transport rejecting private addresses at connection time.

Allowlist mode also supported: pass `allowed_hosts=` for endpoints with known
upstreams (OAuth JWKS, OpenAI, Stripe, MercadoPago).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable

import httpx

from app.core.errors import UpstreamError

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + AWS/GCP metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("ff00::/8"),  # IPv6 multicast
    ipaddress.ip_network("fd00:ec2::/32"),  # Azure / cloud metadata IPv6
]


class SSRFBlocked(UpstreamError):
    type_slug = "ssrf-blocked"
    title = "Outbound request blocked (SSRF defence)"


def _ip_is_blocked(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # unparseable = paranoid block
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True
    return False


def _resolve_and_check(host: str) -> None:
    """Resolve hostname; raise if any A/AAAA points to a blocked range."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFBlocked(f"dns_failed:{host}") from e
    for family, _stype, _proto, _cn, sockaddr in infos:
        addr = sockaddr[0]
        if _ip_is_blocked(addr):
            raise SSRFBlocked(f"private_ip:{host}={addr}")


class _SSRFTransport(httpx.AsyncHTTPTransport):
    """httpx async transport that pre-validates target host before connect."""

    def __init__(self, *, allowed_hosts: Iterable[str] | None = None, **kw) -> None:
        super().__init__(**kw)
        self._allowed = set(h.lower() for h in (allowed_hosts or []))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = (request.url.host or "").lower()
        if self._allowed and host not in self._allowed:
            raise SSRFBlocked(f"host_not_allowlisted:{host}")
        # Resolve + check, in a thread (getaddrinfo is sync).
        import asyncio

        await asyncio.to_thread(_resolve_and_check, host)
        return await super().handle_async_request(request)


def safe_async_client(
    *,
    timeout: float = 10.0,
    allowed_hosts: Iterable[str] | None = None,
) -> httpx.AsyncClient:
    """Drop-in replacement for `httpx.AsyncClient` with SSRF guard active.

    Usage:
        async with safe_async_client(allowed_hosts={"oauth2.googleapis.com"}) as c:
            r = await c.get("https://oauth2.googleapis.com/tokeninfo")
    """
    transport = _SSRFTransport(allowed_hosts=allowed_hosts)
    return httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False)
