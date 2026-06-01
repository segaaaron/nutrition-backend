"""Idempotency helpers — UUID validation, repo replay, conflict detection."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.core.idempotency import (
    CachedResponse,
    IdempotencyConflict,
    IdempotencyRepo,
    fingerprint_body,
    is_whitelisted,
    remember,
    replay_or_remember,
    storage_key,
    validate_idempotency_key,
)


VALID_KEY = "550e8400-e29b-41d4-a716-446655440000"


class FakeRepo:
    """In-memory :class:`IdempotencyRepo` for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[CachedResponse, datetime]] = {}
        self.lock_calls: list[str] = []

    async def acquire_lock(self, storage_key: str) -> None:
        self.lock_calls.append(storage_key)

    async def lookup(self, storage_key: str) -> CachedResponse | None:
        entry = self._store.get(storage_key)
        if entry is None:
            return None
        cached, expires = entry
        if expires < datetime.now(tz=expires.tzinfo):
            return None
        return cached

    async def store(
        self, storage_key: str, cached: CachedResponse, expires_at: datetime
    ) -> None:
        self._store[storage_key] = (cached, expires_at)


def _fake_request(path: str = "/v1/plan/generate") -> Any:
    req = MagicMock()
    req.url.path = path
    return req


def test_validate_idempotency_key_accepts_valid_uuid4() -> None:
    assert validate_idempotency_key(VALID_KEY) == VALID_KEY


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-uuid",
        "",
        "550E8400-E29B-41D4-A716-446655440000",  # uppercase — strict lowercase
        "550e8400-e29b-11d4-a716-446655440000",  # v1, not v4
        "550e8400e29b41d4a716446655440000",  # missing dashes
    ],
)
def test_validate_idempotency_key_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_idempotency_key(bad)
    assert exc.value.http_status == 422  # mapped to 400-equivalent client error
    assert exc.value.extra.get("field") == "Idempotency-Key"


def test_is_whitelisted_matches_exact_routes() -> None:
    assert is_whitelisted("POST", "/v1/plan/generate")
    assert is_whitelisted("POST", "/v1/plan/me/recalibrate")
    assert is_whitelisted("POST", "/v1/profile/me/onboarding")


def test_is_whitelisted_matches_swap_prefix() -> None:
    assert is_whitelisted("POST", "/v1/plan/me/swap/breakfast-2026-06-01")


def test_is_whitelisted_rejects_non_whitelisted() -> None:
    assert not is_whitelisted("GET", "/v1/plan/generate")
    assert not is_whitelisted("POST", "/v1/recipes")


async def test_replay_returns_none_on_miss() -> None:
    repo = FakeRepo()
    out = await replay_or_remember(
        request=_fake_request(),
        repo=repo,
        user_id="u1",
        raw_key=VALID_KEY,
        body=b'{"a":1}',
    )
    assert out is None
    # advisory lock was acquired even on miss — concurrent caller must block.
    assert len(repo.lock_calls) == 1


async def test_replay_returns_cached_on_hit() -> None:
    repo = FakeRepo()
    req = _fake_request()
    skey = storage_key("u1", req.url.path, VALID_KEY)
    cached = CachedResponse(
        body={"plan_id": "abc"},
        status_code=201,
        fingerprint=fingerprint_body(b'{"a":1}'),
    )
    repo._store[skey] = (cached, datetime.max.replace(tzinfo=__import__("datetime").timezone.utc))

    out = await replay_or_remember(
        request=req,
        repo=repo,
        user_id="u1",
        raw_key=VALID_KEY,
        body=b'{"a":1}',
    )
    assert out == cached


async def test_replay_raises_conflict_on_body_mismatch() -> None:
    repo = FakeRepo()
    req = _fake_request()
    skey = storage_key("u1", req.url.path, VALID_KEY)
    cached = CachedResponse(
        body={"plan_id": "abc"},
        status_code=201,
        fingerprint=fingerprint_body(b'{"a":1}'),
    )
    repo._store[skey] = (
        cached,
        datetime.max.replace(tzinfo=__import__("datetime").timezone.utc),
    )

    with pytest.raises(IdempotencyConflict):
        await replay_or_remember(
            request=req,
            repo=repo,
            user_id="u1",
            raw_key=VALID_KEY,
            body=b'{"a":2}',  # different body
        )


async def test_remember_persists_response() -> None:
    repo = FakeRepo()
    req = _fake_request()
    await remember(
        request=req,
        repo=repo,
        user_id="u1",
        raw_key=VALID_KEY,
        body=b'{"a":1}',
        response_body={"plan_id": "abc"},
        status_code=201,
    )
    skey = storage_key("u1", req.url.path, VALID_KEY)
    assert skey in repo._store
    cached, _ = repo._store[skey]
    assert cached.body == {"plan_id": "abc"}
    assert cached.status_code == 201
    assert cached.fingerprint == fingerprint_body(b'{"a":1}')


async def test_replay_invalid_key_raises_before_lookup() -> None:
    repo = FakeRepo()
    with pytest.raises(ValidationError):
        await replay_or_remember(
            request=_fake_request(),
            repo=repo,
            user_id="u1",
            raw_key="not-a-uuid",
            body=b"{}",
        )
    assert repo.lock_calls == []


def test_idempotency_repo_protocol_is_satisfied_by_fake_repo() -> None:
    # Structural typing check — FakeRepo must satisfy the Protocol.
    repo: IdempotencyRepo = FakeRepo()
    assert repo is not None
