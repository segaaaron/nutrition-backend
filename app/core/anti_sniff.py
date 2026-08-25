"""Anti-sniff middleware (OWASP API8 + ASVS V9) — defense-in-depth against
intercepting proxies like Proxyman, Charles, mitmproxy, Burp.

PRIMARY DEFENSE remains SSL pinning on mobile clients. This middleware
adds a secondary signal: detect requests with proxy-tool fingerprints
(via headers) and known-bad User-Agents (curl/wget/python in prod) and
reject or log as security event.

CANNOT prevent sniffing on jailbroken devices with custom CA installed
when SSL pinning is missing client-side. That is mobile team's job.
"""

from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

log = get_logger("security.antisniff")

ANTISNIFF_REJECTS = Counter(
    "antisniff_rejects_total",
    "Requests rejected by anti-sniff middleware",
    ["reason"],
)
ANTISNIFF_SUSPECTS = Counter(
    "antisniff_suspects_total",
    "Suspicious requests logged but not rejected (dev mode or low confidence)",
    ["reason"],
)

# User-Agents typical of MITM proxies / scrapers / automation.
SUSPICIOUS_UA_PATTERNS = re.compile(
    r"(charles|proxyman|burp|fiddler|mitmproxy|wireshark|httptoolkit|"
    r"^curl/|^wget/|python-requests/|httpx/|^okhttp/$|insomnia|postmanruntime)",
    re.IGNORECASE,
)

# Proxy-injected headers that legitimate Cloudflare-only chain shouldn't have.
PROXY_FOOTPRINT_HEADERS = (
    "via",  # often added by intermediate proxies
    "x-charles-proxy",  # Charles signature
    "x-burp-comment",  # Burp signature
    "x-mitm",
)

# Allowed Via prefixes (Cloudflare adds Via "<status> <name>" in some cases).
VIA_ALLOWLIST_PREFIX = ("1.1 cloudflare", "2.0 cloudflare")


def _is_proxy_via(via: str) -> bool:
    """Returns True if Via header smells like a non-CF proxy."""
    v = via.lower().strip()
    if not v:
        return False
    return not any(v.startswith(p) for p in VIA_ALLOWLIST_PREFIX)


class AntiSniffMiddleware(BaseHTTPMiddleware):
    """Detect MITM proxy fingerprints. Production = reject; dev = log only."""

    def __init__(self, app, *, enforce: bool = True) -> None:
        super().__init__(app)
        self._enforce = enforce

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        ua = request.headers.get("user-agent", "")
        reasons: list[str] = []

        if ua and SUSPICIOUS_UA_PATTERNS.search(ua):
            reasons.append("suspicious_ua")

        for h in PROXY_FOOTPRINT_HEADERS:
            if h == "via":
                via = request.headers.get("via", "")
                if _is_proxy_via(via):
                    reasons.append("proxy_via")
            elif request.headers.get(h):
                reasons.append(f"header_{h}")

        if not reasons:
            return await call_next(request)

        # Bypass health/metrics and static images — recipe images are public
        # assets that browsers, CDNs, and curl -I must be able to fetch.
        if request.url.path in ("/healthz", "/readyz", "/metrics") or request.url.path.startswith("/images/"):
            return await call_next(request)

        if self._enforce:
            for r in reasons:
                ANTISNIFF_REJECTS.labels(reason=r).inc()
            log.warning(
                "antisniff.reject",
                reasons=reasons,
                ua=ua[:200],
                path=request.url.path,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "type": "urn:nova:errors:client-fingerprint",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": "client_fingerprint_rejected",
                },
            )

        # Non-enforcing mode: log + pass through.
        for r in reasons:
            ANTISNIFF_SUSPECTS.labels(reason=r).inc()
        log.info(
            "antisniff.suspect",
            reasons=reasons,
            ua=ua[:200],
            path=request.url.path,
        )
        return await call_next(request)
