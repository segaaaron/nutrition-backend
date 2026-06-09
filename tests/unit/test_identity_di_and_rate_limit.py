"""Identity DI and rate-limit resilience tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from redis.exceptions import RedisError

from app.identity.infrastructure import rate_limit as rl_mod
from app.notifications.infrastructure.null_sender import NullEmailSender


def test_get_email_sender_falls_back_to_null_when_resend_key_missing(monkeypatch) -> None:
    import app.core.di as di_mod

    monkeypatch.setattr(di_mod, "get_settings", lambda: SimpleNamespace(email_enabled=True, resend_api_key=""))
    di_mod.get_email_sender.cache_clear()

    sender = di_mod.get_email_sender()

    assert isinstance(sender, NullEmailSender)


@pytest.mark.asyncio
async def test_auth_rate_limit_falls_open_on_redis_down(monkeypatch) -> None:
    monkeypatch.setattr(rl_mod, "get_redis", lambda: (_ for _ in ()).throw(RedisError("redis_down")))

    await rl_mod.rate_limit(scope="auth", identifier="user@example.com", limit_per_min=10)
