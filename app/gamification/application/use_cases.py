"""Gamification queries: progress, level, achievements, leaderboard, celebrations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.gamification.domain.catalog import AchievementDef
from app.gamification.domain.entities import UserLevel
from app.gamification.domain.events import (
    AchievementUnlocked,
    CelebrationTriggered,
)
from app.gamification.infrastructure.repository import (
    SqlGamificationRepository,
    leaderboard_key,
)

_log = get_logger("gamification.use_cases")

CELEBRATION_QUEUE_KEY = "celebrations:queue:{user_id}"


@dataclass(slots=True)
class GetUserProgress:
    repo: SqlGamificationRepository

    async def __call__(self, user_id: UUID) -> dict:
        unlocked = await self.repo.unlocked(user_id)
        points = await self.repo.total_points(user_id)
        level = UserLevel.from_points(points)
        streaks = await self.repo.streaks_for(user_id)
        return {
            "points": points,
            "level": {"value": level.level, "next_level_points": level.next_level_points},
            "streaks": [
                {
                    "type": s.type.value,
                    "value": s.value,
                    "last_day": s.last_day.isoformat() if s.last_day else None,
                }
                for s in streaks
            ],
            "recent_achievements": [
                {"code": a.code, "unlocked_at": a.unlocked_at.isoformat()} for a in unlocked[:5]
            ],
        }


@dataclass(slots=True)
class GetAchievementsCatalog:
    repo: SqlGamificationRepository

    async def __call__(self, user_id: UUID) -> list[dict]:
        unlocked = {a.code for a in await self.repo.unlocked(user_id)}
        return self.repo.catalog_with_progress(unlocked)


@dataclass(slots=True)
class GetLevel:
    repo: SqlGamificationRepository

    async def __call__(self, user_id: UUID) -> dict:
        points = await self.repo.total_points(user_id)
        level = UserLevel.from_points(points)
        return {
            "points": points,
            "level": level.level,
            "next_level_points": level.next_level_points,
        }


@dataclass(slots=True)
class GetLeaderboard:
    redis: Redis

    async def __call__(
        self,
        *,
        country: str,
        period: str = "week",
        limit: int = 20,
    ) -> list[dict]:
        key = leaderboard_key(country=country, period=period)
        try:
            rows = await self.redis.zrevrange(key, 0, limit - 1, withscores=True)
        except RedisError:
            _log.exception("gamification.leaderboard_redis_down", key=key)
            return []
        return [
            {"user_id": uid.decode() if isinstance(uid, bytes) else uid, "score": int(score)}
            for uid, score in rows
        ]


@dataclass(slots=True)
class GetPendingCelebrations:
    redis: Redis

    async def __call__(self, user_id: UUID) -> list[dict]:
        k = CELEBRATION_QUEUE_KEY.format(user_id=user_id)
        try:
            items = await self.redis.lrange(k, 0, -1)
            await self.redis.delete(k)
        except RedisError:
            _log.exception("gamification.celebrations_redis_down", user_id=str(user_id))
            return []
        return [json.loads(x) for x in items]


async def trigger_celebration(
    bus: EventBus,
    redis: Redis,
    *,
    user_id: UUID,
    code: str,
) -> None:
    evt = CelebrationTriggered(
        user_id=user_id,
        code=code,
        at=datetime.now(UTC),
    )
    await bus.publish(evt)
    try:
        await redis.rpush(
            CELEBRATION_QUEUE_KEY.format(user_id=user_id),
            json.dumps({"code": code, "at": evt.at.isoformat()}),
        )
        await redis.expire(CELEBRATION_QUEUE_KEY.format(user_id=user_id), 24 * 3600)
    except RedisError:
        # Celebration queue is best-effort UX glue — Redis down must not
        # block the user-facing flow that enqueued the event. Logged so
        # ops can correlate with broader Redis incidents.
        _log.exception("gamification.celebration_enqueue_failed", user_id=str(user_id))


async def maybe_unlock(
    repo: SqlGamificationRepository,
    bus: EventBus,
    redis: Redis,
    *,
    user_id: UUID,
    achievement: AchievementDef,
) -> None:
    if await repo.has_achievement(user_id=user_id, code=achievement.code):
        return
    inserted = await repo.insert_achievement(user_id=user_id, code=achievement.code)
    if not inserted:
        return
    await bus.publish(
        AchievementUnlocked(
            user_id=user_id,
            code=achievement.code,
            points=achievement.points,
            at=datetime.now(UTC),
        )
    )
    await trigger_celebration(bus, redis, user_id=user_id, code=f"achievement_{achievement.code}")
