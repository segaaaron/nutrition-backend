"""Regression tests for Patrón #2 narrowed except blocks.

Each test injects an exception OUTSIDE the now-narrowed surface and
asserts it propagates (rather than being silently swallowed).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError


# ---------------------------------------------------------------------------
# app/core/security.verify_password — narrowed to argon2 auth failures only.
# Previously bare ``except Exception`` returned False for ANY error,
# including programmer mistakes like passing None.
# ---------------------------------------------------------------------------
def test_verify_password_propagates_non_argon2_errors() -> None:
    from app.core import security

    # argon2.PasswordHasher.verify raises TypeError when fed None (a real
    # bug, not an auth failure). Pre-fix, this returned False silently;
    # post-fix, it must propagate so we surface caller bugs.
    with pytest.raises((TypeError, AttributeError)):
        security.verify_password(None, "$argon2id$v=19$m=65536,t=3,p=4$abc$def")  # type: ignore[arg-type]


def test_verify_password_still_returns_false_on_mismatch() -> None:
    from app.core import security

    h = security.hash_password("right-password")
    assert security.verify_password("wrong-password", h) is False
    assert security.verify_password("right-password", h) is True


# ---------------------------------------------------------------------------
# app/identity/infrastructure/password_hasher.Argon2PasswordHasher.verify
# ---------------------------------------------------------------------------
def test_argon2_password_hasher_propagates_non_argon2_errors() -> None:
    from app.identity.infrastructure.password_hasher import Argon2PasswordHasher

    h = Argon2PasswordHasher()
    with pytest.raises((TypeError, AttributeError)):
        h.verify(None, "$argon2id$v=19$m=65536,t=3,p=4$abc$def")  # type: ignore[arg-type]


def test_argon2_password_hasher_returns_false_on_mismatch() -> None:
    from app.identity.infrastructure.password_hasher import Argon2PasswordHasher

    h = Argon2PasswordHasher()
    digest = h.hash("secret")
    assert h.verify("secret", digest) is True
    assert h.verify("nope", digest) is False


# ---------------------------------------------------------------------------
# app/billing/gateways MercadoPago webhook payload parse — narrowed to
# (JSONDecodeError, UnicodeDecodeError).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mp_webhook_propagates_unexpected_exception() -> None:
    """A non-decode bug inside the json.loads context must NOT be
    coerced to 'mercadopago_webhook_invalid:bad_payload'."""
    import hashlib
    import hmac
    import time
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.billing import gateways
    from app.core.errors import UpstreamError

    secret = "test-secret"
    ts = str(int(time.time()))
    request_id = "req-1"
    payload = b'{"data":{"id":"123"}}'
    manifest = f"id:123;request-id:{request_id};ts:{ts};"
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    sig_header = f"ts={ts},v1={v1}"

    gw = gateways.MercadoPagoGateway()

    fake_settings = SimpleNamespace(mercadopago_webhook_secret=secret)
    with patch.object(gateways, "get_settings", return_value=fake_settings):
        # JSONDecodeError → mapped to UpstreamError (expected).
        with patch.object(
            gateways.json, "loads", side_effect=json.JSONDecodeError("x", "y", 0)
        ):
            with pytest.raises(UpstreamError, match="bad_payload"):
                await gw.verify_webhook(
                    payload=payload, signature=sig_header, request_id=request_id
                )

        # RuntimeError → must propagate raw (narrow surface).
        with patch.object(gateways.json, "loads", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await gw.verify_webhook(
                    payload=payload, signature=sig_header, request_id=request_id
                )


# ---------------------------------------------------------------------------
# app/gamification/application/use_cases — narrowed Redis catchers must
# still let non-Redis exceptions propagate.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_gamification_leaderboard_propagates_non_redis_error() -> None:
    from app.gamification.application.use_cases import GetLeaderboard

    redis = MagicMock()
    redis.zrevrange = AsyncMock(side_effect=RuntimeError("unexpected"))
    lb = GetLeaderboard(redis=redis)
    with pytest.raises(RuntimeError, match="unexpected"):
        await lb(country="AR", period="week", limit=10)


@pytest.mark.asyncio
async def test_gamification_leaderboard_swallows_redis_error() -> None:
    from app.gamification.application.use_cases import GetLeaderboard

    redis = MagicMock()
    redis.zrevrange = AsyncMock(side_effect=RedisError("down"))
    lb = GetLeaderboard(redis=redis)
    result = await lb(country="AR", period="week", limit=10)
    assert result == []


@pytest.mark.asyncio
async def test_gamification_celebrations_propagates_non_redis_error() -> None:
    from app.gamification.application.use_cases import GetPendingCelebrations

    redis = MagicMock()
    redis.lrange = AsyncMock(side_effect=ValueError("non-redis-bug"))
    pop = GetPendingCelebrations(redis=redis)
    with pytest.raises(ValueError, match="non-redis-bug"):
        await pop(uuid4())


@pytest.mark.asyncio
async def test_gamification_celebrations_swallows_redis_error() -> None:
    from app.gamification.application.use_cases import GetPendingCelebrations

    redis = MagicMock()
    redis.lrange = AsyncMock(side_effect=RedisError("down"))
    redis.delete = AsyncMock(side_effect=RedisError("down"))
    pop = GetPendingCelebrations(redis=redis)
    result = await pop(uuid4())
    assert result == []


# ---------------------------------------------------------------------------
# app/core/event_bus.bootstrap importlib catch — narrowed to ImportError.
# A SyntaxError raised at module import time must propagate (forces dev to
# notice broken event module instead of silently dropping its events).
# ---------------------------------------------------------------------------
def test_event_bus_bootstrap_propagates_non_import_error(monkeypatch) -> None:
    import importlib

    from app.core import event_bus

    original = importlib.import_module

    def fake_import(name, package=None):
        if name == "app.identity.domain.events":
            raise RuntimeError("simulated broken module")
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    # bootstrap_event_registry exists per event_bus module; if rename
    # happens, this test surfaces it.
    with pytest.raises(RuntimeError, match="simulated"):
        event_bus._bootstrap_event_registry()
