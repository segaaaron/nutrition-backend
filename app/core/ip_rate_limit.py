"""Per-IP global rate limit middleware (OWASP API4 — Unrestricted Resource Consumption).

Complements per-user Redis sliding window: caps volumetric attacks before
auth check. Bypasses health/metrics/webhooks endpoints (provider IPs).

Sliding window via Redis INCR + EXPIRE. Counter key = `iprl:{minute}:{ip}`.
Returns 429 with Retry-After header when over cap.

IP resolution order (safe against header spoofing):
  1. If request.client.host is in TRUSTED_PROXIES, trust CF-Connecting-IP
     (Cloudflare terminated the TLS) then X-Forwarded-For leftmost hop.
  2. Otherwise use request.client.host directly — no header trust.

TRUSTED_PROXIES must be the Cloudflare egress CIDR ranges or your own
reverse-proxy IPs. Set via env TRUSTED_PROXY_IPS (comma-separated CIDRs).
Defaults to empty set → no proxy header trusted → always uses socket IP.
"""

from __future__ import annotations

import ipaddress
import os
from datetime import UTC, datetime

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import Counter
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.redis import get_redis

IP_RATE_LIMIT_REJECTS = Counter(
    "ip_rate_limit_rejects_total",
    "Requests rejected by per-IP global rate-limit",
    [],
)

DEFAULT_LIMIT_PER_MIN = 600  # generous; per-user limits are tighter
BYPASS_PATH_PREFIXES = (
    "/healthz",
    "/readyz",
    "/metrics",
    "/webhooks/stripe",
    "/webhooks/mercadopago",
)

# RFC 1918 private ranges + loopback are always trusted — they can only
# originate from your own infrastructure (internal LB, Docker network, etc.).
# External clients never present these addresses at the TCP layer.
_ALWAYS_TRUSTED: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
)

# Additional CIDRs from env (e.g., Cloudflare egress ranges).
# Set TRUSTED_PROXY_IPS="103.21.244.0/22,103.22.200.0/22,..." in env.
_raw = os.getenv("TRUSTED_PROXY_IPS", "")
_EXTRA_TRUSTED: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
for _cidr in filter(None, _raw.split(",")):
    try:
        _EXTRA_TRUSTED.append(ipaddress.ip_network(_cidr.strip(), strict=False))
    except ValueError:
        pass

_TRUSTED_PROXY_NETS = list(_ALWAYS_TRUSTED) + _EXTRA_TRUSTED


def _is_trusted_proxy(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _TRUSTED_PROXY_NETS)
    except ValueError:
        return False


def _client_ip(request: Request) -> str:
    socket_host = request.client.host if request.client else None

    # Only trust forwarded headers when the direct connection comes from
    # a known proxy (Cloudflare, internal LB). Prevents header spoofing
    # by clients that connect directly to the VPS.
    if socket_host and _is_trusted_proxy(socket_host):
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip().split(",")[0].strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()

    return socket_host or "unknown"


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit_per_minute: int = DEFAULT_LIMIT_PER_MIN) -> None:
        super().__init__(app)
        self._limit = limit_per_minute

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        path = request.url.path
        if any(path.startswith(p) for p in BYPASS_PATH_PREFIXES):
            return await call_next(request)

        ip = _client_ip(request)
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
        key = f"iprl:{minute}:{ip}"
        try:
            r = get_redis()
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, 70)
            count, _ = await pipe.execute()
        except Exception:  # noqa: BLE001 — Redis down → fail-open (graceful)
            return await call_next(request)

        if int(count) > self._limit:
            IP_RATE_LIMIT_REJECTS.inc()
            return JSONResponse(
                status_code=429,
                content={
                    "type": "urn:nova:errors:rate-limited",
                    "title": "Too Many Requests",
                    "status": 429,
                    "detail": "ip_rate_limit_exceeded",
                },
                headers={"Retry-After": "60", "X-RateLimit-Scope": "ip"},
            )
        return await call_next(request)
