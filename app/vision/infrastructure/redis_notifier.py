"""Redis-pubsub job notifier — channel `user:{id}` for SSE consumers."""
from __future__ import annotations

import json
from uuid import UUID

from app.core.redis import get_redis


class RedisJobNotifier:
    async def notify(self, *, user_id: UUID, channel: str, payload: dict) -> None:
        r = get_redis()
        chan = f"user:{user_id}:{channel}"
        await r.publish(chan, json.dumps(payload, default=str))
