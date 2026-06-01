"""HTTP security headers middleware (OWASP API8 + ASVS V9/V14).

HSTS forces HTTPS for 2y (preload-ready). CSP `default-src 'none'` because
this is a pure JSON API (no HTML rendered). X-Content-Type-Options blocks
MIME sniffing. Permissions-Policy disables browser-level sensor/payment APIs
that we never use.
"""
from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, is_production: bool) -> None:
        super().__init__(app)
        self._prod = is_production

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), payment=(), usb=(), "
            "magnetometer=(), gyroscope=(), accelerometer=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        if self._prod:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response
