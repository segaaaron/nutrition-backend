"""Unit — per-user hourly photo upload rate limit (Capa 4)."""

from __future__ import annotations

from datetime import UTC
from uuid import uuid4

import pytest

from app.core.errors import RateLimited


@pytest.mark.asyncio
async def test_rate_limit_allows_30_blocks_31st(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    from app.core.config import get_settings
    from app.vision.presentation import rate_limit as rl_mod

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_PHOTO_UPLOADS_PER_HOUR", "30")

    monkeypatch.setattr(rl_mod, "get_redis", lambda: fake_redis)

    user_id = uuid4()
    # 30 within budget
    for _ in range(30):
        await rl_mod.check_photo_upload_rate_limit(user_id)

    # 31st must raise
    with pytest.raises(RateLimited) as exc_info:
        await rl_mod.check_photo_upload_rate_limit(user_id)

    # Spec response shape: error + retry_after surfaced via extra fields.
    extra = exc_info.value.extra
    assert extra["error"] == "rate_limit_exceeded"
    assert isinstance(extra["retry_after"], int)
    assert 1 <= extra["retry_after"] <= 3600

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rate_limit_key_format(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    """Key must be `photo_uploads:{user_id}:{YYYY-MM-DD-HH}` per spec."""
    from datetime import datetime

    from app.core.config import get_settings
    from app.vision.presentation import rate_limit as rl_mod

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_PHOTO_UPLOADS_PER_HOUR", "30")
    monkeypatch.setattr(rl_mod, "get_redis", lambda: fake_redis)

    user_id = uuid4()
    await rl_mod.check_photo_upload_rate_limit(user_id)

    bucket = datetime.now(UTC).strftime("%Y-%m-%d-%H")
    expected_key = f"photo_uploads:{user_id}:{bucket}"
    val = await fake_redis.get(expected_key)
    assert val == "1"

    get_settings.cache_clear()
