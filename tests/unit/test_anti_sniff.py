"""Anti-sniff middleware tests (OWASP API8)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.anti_sniff import AntiSniffMiddleware


def _client(enforce: bool = True) -> TestClient:
    app = FastAPI()
    app.add_middleware(AntiSniffMiddleware, enforce=enforce)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/healthz")
    def health():
        return {"ok": True}

    return TestClient(app)


def test_legitimate_mobile_ua_passes():
    c = _client(enforce=True)
    r = c.get("/ping", headers={"User-Agent": "NOVA-iOS/1.0 CFNetwork/1.0"})
    assert r.status_code == 200


def test_curl_rejected_in_production():
    c = _client(enforce=True)
    r = c.get("/ping", headers={"User-Agent": "curl/8.0"})
    assert r.status_code == 403
    assert r.json()["detail"] == "client_fingerprint_rejected"


def test_proxyman_signature_rejected():
    c = _client(enforce=True)
    r = c.get("/ping", headers={"User-Agent": "Proxyman/4.0"})
    assert r.status_code == 403


def test_burp_via_header_rejected():
    c = _client(enforce=True)
    r = c.get(
        "/ping",
        headers={
            "User-Agent": "NOVA-iOS/1.0",
            "Via": "1.1 burp-proxy",
        },
    )
    assert r.status_code == 403


def test_cloudflare_via_allowed():
    c = _client(enforce=True)
    r = c.get(
        "/ping",
        headers={
            "User-Agent": "NOVA-iOS/1.0",
            "Via": "1.1 cloudflare",
        },
    )
    assert r.status_code == 200


def test_dev_mode_logs_only_no_reject():
    c = _client(enforce=False)
    r = c.get("/ping", headers={"User-Agent": "curl/8.0"})
    assert r.status_code == 200


def test_health_bypass_allows_curl():
    c = _client(enforce=True)
    r = c.get("/healthz", headers={"User-Agent": "curl/8.0"})
    assert r.status_code == 200


def test_python_requests_rejected():
    c = _client(enforce=True)
    r = c.get("/ping", headers={"User-Agent": "python-requests/2.32"})
    assert r.status_code == 403


def test_charles_proxy_header_rejected():
    c = _client(enforce=True)
    r = c.get(
        "/ping",
        headers={
            "User-Agent": "NOVA-iOS/1.0",
            "X-Charles-Proxy": "1",
        },
    )
    assert r.status_code == 403
