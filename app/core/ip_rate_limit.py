"""Per-IP global rate limit middleware (OWASP API4 — Unrestricted Resource Consumption).

Complements per-user Redis sliding window: caps volumetric attacks before
auth check. Bypasses health/metrics/webhooks endpoints (provider IPs).

Sliding window via Redis INCR + EXPIRE. Counter key = `iprl:{minute}:{ip}`.
Returns 429 with Retry-After header when over cap. Honours CF-Connecting-IP
when behind Cloudflare; falls back to X-Forwarded-For first hop, then
request.client.host.
"""
from __future__ import annotations

from datetime import datetime, timezone

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
    "/healthz", "/readyz", "/metrics",
    "/webhooks/stripe", "/webhooks/mercadopago",
)


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit_per_minute: int = DEFAULT_LIMIT_PER_MIN) -> None:
        super().__init__(app)
        self._limit = limit_per_minute

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        path = request.url.path
        if any(path.startswith(p) for p in BYPASS_PATH_PREFIXES):
            return await call_next(request)

        ip = _client_ip(request)
        minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
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
