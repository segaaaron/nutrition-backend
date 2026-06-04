"""Security headers middleware tests (OWASP API8 + ASVS V9/V14).

Use isolated FastAPI instance with just the middleware to avoid loading the
full router graph (which has a pre-existing 204-with-body issue elsewhere).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security_headers import SecurityHeadersMiddleware


def _client(is_prod: bool) -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, is_production=is_prod)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def test_security_headers_present_on_response():
    r = _client(is_prod=False).get("/ping")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "strict-origin-when-cross-origin" in r.headers["Referrer-Policy"]
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert "geolocation=()" in r.headers["Permissions-Policy"]
    assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"


def test_hsts_only_in_production():
    assert "Strict-Transport-Security" not in _client(is_prod=False).get("/ping").headers


def test_hsts_set_in_production():
    hsts = _client(is_prod=True).get("/ping").headers.get("Strict-Transport-Security", "")
    assert "max-age=63072000" in hsts
    assert "preload" in hsts


def test_csp_blocks_framing():
    csp = _client(is_prod=False).get("/ping").headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp


def test_permissions_policy_disables_sensitive_apis():
    pp = _client(is_prod=False).get("/ping").headers["Permissions-Policy"]
    for feature in ("geolocation", "camera", "microphone", "payment"):
        assert f"{feature}=()" in pp
