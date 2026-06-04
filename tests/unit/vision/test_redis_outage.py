"""Unit — MEDIUM-2 fix: photo-upload rate limiter fails CLOSED (503) when
Redis is unreachable, not open (silent pass).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.mark.asyncio
async def test_rate_limit_fails_closed_on_redis_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings
    from app.vision.presentation import rate_limit as rl_mod

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_PHOTO_UPLOADS_PER_HOUR", "30")

    class _DeadPipeline:
        def incr(self, *_a, **_k):
            return None

        def expire(self, *_a, **_k):
            return None

        async def execute(self):
            raise RedisConnectionError("connection refused")

    class _DeadRedis:
        def pipeline(self):
            return _DeadPipeline()

    monkeypatch.setattr(rl_mod, "get_redis", lambda: _DeadRedis())

    with pytest.raises(rl_mod.ServiceUnavailable) as exc_info:
        await rl_mod.check_photo_upload_rate_limit(uuid4())

    assert exc_info.value.http_status == 503
    assert exc_info.value.extra["retry_after"] == 30
    get_settings.cache_clear()
