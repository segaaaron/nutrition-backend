"""Redis hot-cache for the active plan (TTL 300s).

Invalidated by `complete_meal` and `swap_meal` use cases so the cached
representation is never stale by more than one user action.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from redis.asyncio import Redis


@dataclass(slots=True)
class ActivePlanCache:
    redis: Redis
    ttl_s: int = 300

    @staticmethod
    def _key(user_id: UUID) -> str:
        return f"plan:active:{user_id}"

    async def get(self, user_id: UUID) -> dict[str, Any] | None:
        raw = await self.redis.get(self._key(user_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return None

    async def set(self, user_id: UUID, payload: dict[str, Any]) -> None:
        await self.redis.set(self._key(user_id), json.dumps(payload, default=str), ex=self.ttl_s)

    async def invalidate(self, user_id: UUID) -> None:
        await self.redis.delete(self._key(user_id))
