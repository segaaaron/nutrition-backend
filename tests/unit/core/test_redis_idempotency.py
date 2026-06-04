"""Redis-backed idempotency helper used by `POST /plans` and
`POST /logs/food/text`.

Contract:
    - First call -> miss, returns (storage_key, None).
    - `remember_redis` persists body for 24h.
    - Second call with same body -> hit, returns (storage_key, cached_body).
    - Same key + different body -> raises IdempotencyConflict.
    - Missing key header -> ValueError("idempotency_key_required").
    - Malformed UUID4 key -> ValidationError (from validate_idempotency_key).
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.core.idempotency import (
    IdempotencyConflict,
    lookup_redis,
    remember_redis,
    require_idempotency_key,
)

VALID_KEY = "550e8400-e29b-41d4-a716-446655440000"


class FakeRedis:
    """Tiny fake. Mirrors `redis.asyncio.Redis.get/set` async surface."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, k: str) -> str | None:
        return self._store.get(k)

    async def set(self, k: str, v: str, ex: int | None = None) -> bool:
        self._store[k] = v
        return True


async def test_lookup_miss_returns_none() -> None:
    redis = FakeRedis()
    skey, cached = await lookup_redis(
        redis=redis,
        user_id="u1",
        path="/plans",
        raw_key=VALID_KEY,
        body=b'{"a":1}',
    )
    assert cached is None
    assert skey.startswith("idem:")


async def test_remember_then_lookup_hits() -> None:
    redis = FakeRedis()
    skey, _ = await lookup_redis(
        redis=redis,
        user_id="u1",
        path="/plans",
        raw_key=VALID_KEY,
        body=b'{"a":1}',
    )
    await remember_redis(
        redis=redis,
        storage_key=skey,
        body=b'{"a":1}',
        response_body={"job_id": "abc"},
        status_code=202,
    )
    _, cached = await lookup_redis(
        redis=redis,
        user_id="u1",
        path="/plans",
        raw_key=VALID_KEY,
        body=b'{"a":1}',
    )
    assert cached is not None
    assert cached.body == {"job_id": "abc"}
    assert cached.status_code == 202


async def test_lookup_body_mismatch_raises_conflict() -> None:
    redis = FakeRedis()
    skey, _ = await lookup_redis(
        redis=redis,
        user_id="u1",
        path="/plans",
        raw_key=VALID_KEY,
        body=b'{"a":1}',
    )
    await remember_redis(
        redis=redis,
        storage_key=skey,
        body=b'{"a":1}',
        response_body={"job_id": "abc"},
        status_code=202,
    )
    with pytest.raises(IdempotencyConflict):
        await lookup_redis(
            redis=redis,
            user_id="u1",
            path="/plans",
            raw_key=VALID_KEY,
            body=b'{"a":2}',  # different body
        )


def test_require_idempotency_key_rejects_missing() -> None:
    with pytest.raises(ValidationError) as exc:
        require_idempotency_key(None)
    assert exc.value.detail == "idempotency_key_required"


def test_require_idempotency_key_rejects_malformed() -> None:
    with pytest.raises(ValidationError):
        require_idempotency_key("not-a-uuid")


def test_require_idempotency_key_accepts_valid() -> None:
    assert require_idempotency_key(VALID_KEY) == VALID_KEY


async def test_lookup_key_isolation_per_user_and_path() -> None:
    """Same Idempotency-Key value across users / paths must NOT collide."""
    redis = FakeRedis()
    skey_a, _ = await lookup_redis(
        redis=redis,
        user_id="u1",
        path="/plans",
        raw_key=VALID_KEY,
        body=b"{}",
    )
    skey_b, _ = await lookup_redis(
        redis=redis,
        user_id="u2",
        path="/plans",
        raw_key=VALID_KEY,
        body=b"{}",
    )
    skey_c, _ = await lookup_redis(
        redis=redis,
        user_id="u1",
        path="/logs/food/text",
        raw_key=VALID_KEY,
        body=b"{}",
    )
    assert skey_a != skey_b
    assert skey_a != skey_c
    assert skey_b != skey_c
