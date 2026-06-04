"""Redis-pubsub job notifier — channel `user:{id}` for SSE consumers."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.redis import get_redis


class RedisJobNotifier:
    async def notify(
        self,
        *,
        user_id: UUID,
        channel: str,
        # Any: SSE payload schema varies per channel; serialised via json.dumps.
        payload: dict[str, Any],
    ) -> None:
        r = get_redis()
        chan = f"user:{user_id}:{channel}"
        await r.publish(chan, json.dumps(payload, default=str))
