"""Contract test — `POST /logs/food` (manual) idempotency parity with `/text`.

Manual log was previously best-effort dedup via SQL ``ON CONFLICT`` only and
did not enforce the ``Idempotency-Key`` header. This test pins the upgraded
behaviour (Sprint hygiene fix):

    - Mandatory UUIDv4 ``Idempotency-Key`` header.
    - Same key + same body within 24 h -> identical 201, handler runs once.
    - Same key + different body -> 409.
    - Missing or malformed key -> 422.

We mirror the production handler at the contract level using a minimal
FastAPI app so we don't pull in DB / auth fixtures.
"""

from __future__ import annotations

import json
from typing import Annotated

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
    app = FastAPI()
    register_exception_handlers(app)
    register_problem_handlers(app)

    USER_ID = "user-abc"

    @app.post("/logs/food", status_code=status.HTTP_201_CREATED)
    async def log_food_manual(
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
        payload = {"food_log_ids": [f"flog-{counter['handler_calls']}"]}
        await remember_redis(
            redis=redis,
            storage_key=skey,
            body=raw_body,
            response_body=payload,
            status_code=status.HTTP_201_CREATED,
        )
        return Response(
            content=json.dumps(payload),
            media_type="application/json",
            status_code=status.HTTP_201_CREATED,
        )

    return app


def test_first_call_runs_handler_and_returns_201() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    r = client.post(
        "/logs/food",
        json={"meal_time": "lunch", "free_text_name": "apple", "amount_g": "150"},
        headers={"Idempotency-Key": VALID_KEY},
    )
    assert r.status_code == 201
    assert r.json()["food_log_ids"] == ["flog-1"]
    assert counter["handler_calls"] == 1


def test_replay_same_key_same_body_returns_cached_no_second_handler_call() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    headers = {"Idempotency-Key": VALID_KEY}
    body = {"meal_time": "lunch", "free_text_name": "apple", "amount_g": "150"}

    r1 = client.post("/logs/food", json=body, headers=headers)
    r2 = client.post("/logs/food", json=body, headers=headers)

    assert r1.status_code == r2.status_code == 201
    assert r1.json() == r2.json()
    assert counter["handler_calls"] == 1


def test_same_key_different_body_returns_409_conflict() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    headers = {"Idempotency-Key": VALID_KEY}

    r1 = client.post(
        "/logs/food",
        json={"meal_time": "lunch", "free_text_name": "apple", "amount_g": "150"},
        headers=headers,
    )
    r2 = client.post(
        "/logs/food",
        json={"meal_time": "dinner", "free_text_name": "apple", "amount_g": "150"},
        headers=headers,
    )

    assert r1.status_code == 201
    assert r2.status_code == 409
    assert counter["handler_calls"] == 1


def test_missing_idempotency_key_returns_422() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    r = client.post(
        "/logs/food",
        json={"meal_time": "lunch", "free_text_name": "apple", "amount_g": "150"},
    )
    assert r.status_code == 422
    assert counter.get("handler_calls", 0) == 0


def test_malformed_idempotency_key_returns_422() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    r = client.post(
        "/logs/food",
        json={"meal_time": "lunch", "free_text_name": "apple", "amount_g": "150"},
        headers={"Idempotency-Key": "not-a-uuid"},
    )
    assert r.status_code == 422


def test_different_idempotency_key_runs_handler_again() -> None:
    redis = FakeRedis()
    counter: dict[str, int] = {}
    client = TestClient(_build_app(redis, counter))
    body = {"meal_time": "lunch", "free_text_name": "apple", "amount_g": "150"}

    client.post("/logs/food", json=body, headers={"Idempotency-Key": VALID_KEY})
    client.post("/logs/food", json=body, headers={"Idempotency-Key": OTHER_KEY})

    assert counter["handler_calls"] == 2
