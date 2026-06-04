"""Per-IP rate-limit middleware tests (OWASP API4)."""

from __future__ import annotations

from collections import defaultdict

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.ip_rate_limit import IpRateLimitMiddleware, _client_ip


class _CountingRedis:
    """Minimal in-memory Redis substitute supporting pipeline + incr + expire."""

    def __init__(self):
        self.counters: dict[str, int] = defaultdict(int)

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self._key: str | None = None

            def incr(self, key):
                outer.counters[key] += 1
                self._key = key
                return self

            def expire(self, key, ttl):
                return self

            async def execute(self):
                return [outer.counters[self._key], True]

        return _Pipe()


def _app(limit: int = 3) -> tuple[TestClient, _CountingRedis]:
    redis = _CountingRedis()
    app = FastAPI()

    # Patch BEFORE adding middleware so all dispatch calls see the fake.
    from app.core import ip_rate_limit as mod

    mod.get_redis = lambda: redis  # type: ignore[assignment]

    app.add_middleware(IpRateLimitMiddleware, limit_per_minute=limit)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/healthz")
    def health():
        return {"ok": True}

    return TestClient(app), redis


def test_under_limit_passes():
    client, _ = _app(limit=5)
    for _ in range(3):
        assert client.get("/ping").status_code == 200


def test_over_limit_rejects_429():
    client, _ = _app(limit=2)
    client.get("/ping")
    client.get("/ping")
    r = client.get("/ping")
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "60"
    assert r.headers["X-RateLimit-Scope"] == "ip"


def test_health_endpoint_bypassed():
    client, _ = _app(limit=1)
    for _ in range(10):
        assert client.get("/healthz").status_code == 200


def test_client_ip_prefers_cloudflare_header():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [
            (b"cf-connecting-ip", b"203.0.113.5"),
            (b"x-forwarded-for", b"198.51.100.1"),
        ],
        "client": ("10.0.0.1", 1234),
    }
    req = Request(scope)
    assert _client_ip(req) == "203.0.113.5"


def test_client_ip_falls_back_to_xff_first_hop():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [
            (b"x-forwarded-for", b"203.0.113.5, 10.0.0.1, 10.0.0.2"),
        ],
        "client": ("10.0.0.1", 1234),
    }
    req = Request(scope)
    assert _client_ip(req) == "203.0.113.5"


def test_redis_down_fails_open(monkeypatch):
    def boom():
        raise RuntimeError("redis_down")

    monkeypatch.setattr("app.core.ip_rate_limit.get_redis", boom)
    app = FastAPI()
    app.add_middleware(IpRateLimitMiddleware, limit_per_minute=1)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.status_code == 200  # graceful fallthrough
