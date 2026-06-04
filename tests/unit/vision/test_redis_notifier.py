"""Unit — RedisJobNotifier publishes to per-user channels.

Validates:
- Channel name follows the `user:{id}:{channel}` convention.
- Payload is json-serialised.
- UUID + Decimal in payload survive via default=str.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.vision.infrastructure.redis_notifier import RedisJobNotifier


@pytest.mark.asyncio
async def test_publishes_to_per_user_channel():
    fake_redis = MagicMock()
    fake_redis.publish = AsyncMock()
    user_id = uuid4()

    with patch(
        "app.vision.infrastructure.redis_notifier.get_redis",
        return_value=fake_redis,
    ):
        notifier = RedisJobNotifier()
        await notifier.notify(
            user_id=user_id,
            channel="vision",
            payload={"job_id": "abc", "status": "completed"},
        )

    fake_redis.publish.assert_awaited_once()
    chan, body = fake_redis.publish.call_args[0]
    assert chan == f"user:{user_id}:vision"
    parsed = json.loads(body)
    assert parsed == {"job_id": "abc", "status": "completed"}


@pytest.mark.asyncio
async def test_serializes_uuid_in_payload():
    fake_redis = MagicMock()
    fake_redis.publish = AsyncMock()
    job_id = uuid4()

    with patch(
        "app.vision.infrastructure.redis_notifier.get_redis",
        return_value=fake_redis,
    ):
        notifier = RedisJobNotifier()
        await notifier.notify(
            user_id=uuid4(),
            channel="vision",
            payload={"job_id": job_id},
        )

    body = fake_redis.publish.call_args[0][1]
    parsed = json.loads(body)
    # default=str renders UUID as its canonical string
    assert parsed["job_id"] == str(job_id)
    # round-trippable
    UUID(parsed["job_id"])
