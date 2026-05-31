"""Gamification SQL repository — streaks, achievements, leaderboard."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gamification.domain.catalog import CATALOG, AchievementDef
from app.gamification.domain.entities import Achievement, Streak, StreakType


class SqlGamificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def streaks_for(self, user_id: UUID) -> list[Streak]:
        rows = (await self.s.execute(text("""
            SELECT user_id, type, value, last_day FROM streaks WHERE user_id = :uid
        """), {"uid": str(user_id)})).mappings().all()
        return [
            Streak(
                user_id=r["user_id"], type=StreakType(r["type"]),
                value=r["value"], last_day=r["last_day"],
            ) for r in rows
        ]

    async def streak(self, *, user_id: UUID, type_: StreakType) -> Streak | None:
        r = (await self.s.execute(text("""
            SELECT user_id, type, value, last_day FROM streaks
             WHERE user_id = :uid AND type = :t
        """), {"uid": str(user_id), "t": type_.value})).mappings().first()
        if not r:
            return None
        return Streak(
            user_id=r["user_id"], type=StreakType(r["type"]),
            value=r["value"], last_day=r["last_day"],
        )

    async def unlocked(self, user_id: UUID) -> list[Achievement]:
        rows = (await self.s.execute(text("""
            SELECT user_id, code, unlocked_at FROM achievements WHERE user_id = :uid
             ORDER BY unlocked_at DESC
        """), {"uid": str(user_id)})).mappings().all()
        return [Achievement(**dict(r)) for r in rows]

    async def has_achievement(self, *, user_id: UUID, code: str) -> bool:
        r = (await self.s.execute(text("""
            SELECT 1 FROM achievements WHERE user_id = :uid AND code = :c
        """), {"uid": str(user_id), "c": code})).first()
        return r is not None

    async def insert_achievement(self, *, user_id: UUID, code: str) -> bool:
        """Returns True if newly inserted (i.e. just unlocked)."""
        r = await self.s.execute(text("""
            INSERT INTO achievements (user_id, code) VALUES (:uid, :c)
            ON CONFLICT (user_id, code) DO NOTHING
            RETURNING 1
        """), {"uid": str(user_id), "c": code})
        return r.first() is not None

    async def total_points(self, user_id: UUID) -> int:
        unlocked = await self.unlocked(user_id)
        codes = {a.code for a in unlocked}
        return sum(a.points for a in CATALOG if a.code in codes)

    def catalog_with_progress(
        self, unlocked: set[str],
    ) -> list[dict]:
        out: list[dict] = []
        for a in CATALOG:
            out.append({
                "code": a.code, "points": a.points, "icon": a.icon,
                "names": a.names, "descriptions": a.descriptions,
                "unlocked": a.code in unlocked,
            })
        return out


# --- Leaderboard (Redis sorted set, scoped by country+period) ---


def leaderboard_key(*, country: str, period: str) -> str:
    return f"leaderboard:{country.lower()}:{period}"
