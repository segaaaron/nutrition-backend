"""Food-log query / delete / aggregate use cases.

Read-side leans on a 60s Redis TTL cache for `daily_totals` since clients
poll it once per second from the dashboard. The cache key is invalidated by
the FoodLogged subscriber registered in `app.tracking.event_handlers`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from redis.asyncio import Redis

from app.core.event_bus import EventBus
from app.tracking.domain.food_log import (
    DailyTotals,
    FoodLog,
    FoodLogSearchQuery,
)
from app.tracking.infrastructure.food_log_repository import SqlFoodLogRepository

# RDA targets (adult baseline — see ADR-0002). Used to compute % satisfied
# for the micros gap dashboard; clinical agent overrides per condition.
RDA_DEFAULTS: dict[str, float] = {
    "calcium_mg": 1000.0,
    "iron_mg": 8.0,
    "magnesium_mg": 400.0,
    "potassium_mg": 3500.0,
    "vitamin_a_mcg": 900.0,
    "vitamin_c_mg": 90.0,
    "vitamin_d_mcg": 15.0,
    "vitamin_b12_mcg": 2.4,
    "folate_mcg": 400.0,
    "zinc_mg": 11.0,
    "omega3_g": 1.6,
}


def _cache_key_totals(user_id: UUID, on: date) -> str:
    return f"tracking:daily_totals:{user_id}:{on.isoformat()}"


@dataclass(slots=True)
class QueryFoodLogs:
    repo: SqlFoodLogRepository

    async def __call__(self, query: FoodLogSearchQuery) -> tuple[list[FoodLog], str | None]:
        return await self.repo.search(query)


@dataclass(slots=True)
class DeleteFoodLog:
    repo: SqlFoodLogRepository
    bus: EventBus
    redis: Redis | None = None

    async def __call__(
        self, *, user_id: UUID, log_id: UUID, reason: str | None = None,
    ) -> None:
        await self.repo.delete(user_id=user_id, log_id=log_id, reason=reason)
        if self.redis is not None:
            await self.redis.delete(_cache_key_totals(user_id, date.today()))


@dataclass(slots=True)
class GetDailyTotals:
    repo: SqlFoodLogRepository
    redis: Redis | None = None

    async def __call__(self, *, user_id: UUID, on: date | None = None) -> DailyTotals:
        on = on or date.today()
        if self.redis is not None:
            cached = await self.redis.get(_cache_key_totals(user_id, on))
            if cached:
                import json
                d = json.loads(cached)
                return DailyTotals(
                    date=on, kcal=d["kcal"], protein_g=d["protein_g"],
                    carbs_g=d["carbs_g"], fat_g=d["fat_g"],
                    fiber_g=d.get("fiber_g", 0), sugar_g=d.get("sugar_g", 0),
                    sodium_mg=d.get("sodium_mg", 0),
                )
        totals = await self.repo.daily_totals(user_id=user_id, on=on)
        if self.redis is not None and on == date.today():
            import json
            await self.redis.set(
                _cache_key_totals(user_id, on),
                json.dumps(totals.as_dict()),
                ex=60,
            )
        return totals


@dataclass(slots=True)
class GetMacrosTrend:
    repo: SqlFoodLogRepository

    async def __call__(self, *, user_id: UUID, window_days: int = 30) -> dict:
        rows = await self.repo.trend(user_id=user_id, window_days=window_days)
        n = max(len(rows), 1)
        avg = {
            "kcal":      round(sum(r["kcal"] for r in rows) / n, 1),
            "protein_g": round(sum(r["protein_g"] for r in rows) / n, 1),
            "carbs_g":   round(sum(r["carbs_g"] for r in rows) / n, 1),
            "fat_g":     round(sum(r["fat_g"] for r in rows) / n, 1),
        }
        return {"window_days": window_days, "points": rows, "rolling_avg": avg}


@dataclass(slots=True)
class GetMicrosToday:
    repo: SqlFoodLogRepository

    async def __call__(
        self, *, user_id: UUID, rda_overrides: dict[str, float] | None = None,
    ) -> dict:
        totals = await self.repo.micros_today(user_id=user_id)
        targets = {**RDA_DEFAULTS, **(rda_overrides or {})}
        gaps: dict[str, dict] = {}
        for nutrient, target in targets.items():
            current = float(totals.get(nutrient, 0.0))
            pct = round(min(100.0, current / target * 100.0), 1) if target else 0.0
            gaps[nutrient] = {
                "current": current, "target": target,
                "pct": pct, "deficit": max(0.0, round(target - current, 4)),
            }
        return {"totals": totals, "gaps": gaps}
