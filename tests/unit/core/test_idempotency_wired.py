"""Integration-style contract tests for Idempotency-Key wiring on the two
endpoints added in D12:

    POST /plans              (status 202)
    POST /logs/food/text     (status 201)

We build minimal FastAPI apps mirroring the production handler bodies, with
the Redis client and any side-effecting collaborator stubbed. The point is
to assert the *contract* — replay returns identical body + status without
running the handler twice — not the real Arq enqueue or SQL writes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, Header, Request, Response, status
from fastapi.testclient import TestClient

from app.core.errors import ConflictError, register_exception_handlers
from app.core.idempotency import (
    IdempotencyConflict,
    cached_to_response,
    lookup_redis,
    remember_redis,
    require_idempotency_key,
)
from app.core.problem_details import register_problem_handlers

VALID_KEY = "550e8400-e29b-41d4-a716-446655440000"
OTHER_KEY = "550e8400-e29b-41d4-a716-446655440001"


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, k: str) -> str | None:
        return self._store.get(k)

    async def set(self, k: str, v: str, ex: int | None = None) -> bool:
        self._store[k] = v
        return True


def _build_app(redis: FakeRedis, counter: dict[str, int]) -> FastAPI:
    """Mirror the production /plans handler at the contract level."""
    app = FastAPI()
    register_exception_handlers(app)
    register_problem_handlers(app)

    USER_ID = "user-abc"

    @app.post("/plans", status_code=status.HTTP_202_ACCEPTED)
    async def create_plan(
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> Response:
        key = require_idempotency_key(idempotency_key)
        raw_body = await request.body()
        try:
            skey, cached = await lookup_redis(
                redis=redis,
                user_id=USER_ID,
                path=request.url.path,
                raw_key=key,
                body=raw_body,
            )
        except IdempotencyConflict as exc:
            raise ConflictError("idempotency_body_mismatch") from exc
        if cached is not None:
            return cached_to_response(cached)

        counter["handler_calls"] = counter.get("handler_calls", 0) + 1
        payload = {"job_id": f"job-{counter['handler_calls']}", "status": "queued"}
        await remember_redis(
            redis=redis,
            storage_key=skey,
            body=raw_body,
            response_body=payload,
            status_code=status.HTTP_202_ACCEPTED,
        )
        return Response(
            content=__import__("json").dumps(payload),
            media_type="application/json",
            status_code=status.HTTP_202_ACCEPTED,
        )

    return app


def test_first_call_runs_handler_and_returns_202() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    r = client.post("/plans", json={"type": "weekly"}, headers={"Idempotency-Key": VALID_KEY})
    assert r.status_code == 202
    assert r.json()["job_id"] == "job-1"
    assert counter["handler_calls"] == 1


def test_replay_same_key_same_body_returns_cached_no_second_handler_call() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    headers = {"Idempotency-Key": VALID_KEY}
    body: dict[str, Any] = {"type": "weekly"}

    r1 = client.post("/plans", json=body, headers=headers)
    r2 = client.post("/plans", json=body, headers=headers)

    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()
    # Handler ran exactly once — second call short-circuited via Redis.
    assert counter["handler_calls"] == 1


def test_same_key_different_body_returns_409_conflict() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    headers = {"Idempotency-Key": VALID_KEY}

    r1 = client.post("/plans", json={"type": "weekly"}, headers=headers)
    r2 = client.post("/plans", json={"type": "monthly"}, headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 409
    assert counter["handler_calls"] == 1


def test_missing_idempotency_key_returns_422() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    r = client.post("/plans", json={"type": "weekly"})
    assert r.status_code == 422
    assert counter.get("handler_calls", 0) == 0


def test_malformed_idempotency_key_returns_422() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    r = client.post(
        "/plans",
        json={"type": "weekly"},
        headers={"Idempotency-Key": "not-a-uuid"},
    )
    assert r.status_code == 422


def test_different_idempotency_key_runs_handler_again() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))

    client.post("/plans", json={"type": "weekly"}, headers={"Idempotency-Key": VALID_KEY})
    client.post("/plans", json={"type": "weekly"}, headers={"Idempotency-Key": OTHER_KEY})

    assert counter["handler_calls"] == 2
