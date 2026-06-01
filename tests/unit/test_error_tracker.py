"""Local error tracker tests — replaces Sentry tests."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.error_tracker import (
    ErrorTrackerMiddleware,
    clear_ring,
    record_error,
    recent_errors,
)


def _ring_reset():
    clear_ring()


def test_record_error_stores_in_ring():
    _ring_reset()
    try:
        raise ValueError("boom")
    except ValueError as e:
        record_error(exc=e, path="/v1/test", user_id="u-1", request_id="r-1")
    errors = recent_errors(limit=10)
    assert len(errors) == 1
    assert errors[0]["type"] == "ValueError"
    assert errors[0]["message"] == "boom"
    assert errors[0]["path"] == "/v1/test"
    assert errors[0]["user_id"] == "u-1"
    assert errors[0]["request_id"] == "r-1"
    assert isinstance(errors[0]["traceback"], list)


def test_ring_caps_at_500():
    _ring_reset()
    for i in range(510):
        try:
            raise RuntimeError(f"err-{i}")
        except RuntimeError as e:
            record_error(exc=e)
    errors = recent_errors(limit=600)
    assert len(errors) == 500
    assert errors[0]["message"] == "err-509"
    assert errors[-1]["message"] == "err-10"


def test_record_error_never_raises_even_with_bad_input():
    """Tracker must be best-effort. Failure inside tracker must not bubble."""
    _ring_reset()
    record_error(exc=Exception("ok"), path="/", extra={"weird": object()})
    assert len(recent_errors()) == 1


def test_middleware_captures_unhandled():
    _ring_reset()
    app = FastAPI()
    app.add_middleware(ErrorTrackerMiddleware)

    @app.get("/boom")
    def boom():
        raise RuntimeError("middleware_test_boom")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    errors = recent_errors()
    assert any(e["type"] == "RuntimeError" for e in errors)
    assert any(e["path"] == "/boom" for e in errors)


def test_middleware_passes_through_success():
    _ring_reset()
    app = FastAPI()
    app.add_middleware(ErrorTrackerMiddleware)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ok")
    assert r.status_code == 200
    assert len(recent_errors()) == 0


def test_clear_ring_returns_count():
    _ring_reset()
    for _ in range(5):
        try:
            raise ValueError("x")
        except ValueError as e:
            record_error(exc=e)
    cleared = clear_ring()
    assert cleared == 5
    assert recent_errors() == []
