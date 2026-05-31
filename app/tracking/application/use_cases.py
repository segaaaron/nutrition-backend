"""Tracking use cases: log water, log weight, get weight trend."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.core.event_bus import EventBus
from app.tracking.domain.entities import WaterLog, WeightLog
from app.tracking.domain.events import WaterLogged, WeightLogged
from app.tracking.infrastructure.repositories import (
    SqlWaterLogRepository,
    SqlWeightLogRepository,
)


@dataclass(slots=True)
class LogWater:
    repo: SqlWaterLogRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID, ml: int) -> int:
        now = datetime.now(timezone.utc)
        await self.repo.append(WaterLog(user_id=user_id, time=now, ml=ml))
        await self.bus.publish(WaterLogged(user_id=user_id, ml=ml, at=now))
        return await self.repo.total_today(user_id)


@dataclass(slots=True)
class LogWeight:
    repo: SqlWeightLogRepository
    bus: EventBus

    async def __call__(
        self, *, user_id: UUID, weight_kg: Decimal,
        body_fat_pct: Decimal | None = None, waist_cm: Decimal | None = None,
        photo_url: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        await self.repo.append(WeightLog(
            user_id=user_id, time=now, weight_kg=weight_kg,
            body_fat_pct=body_fat_pct, waist_cm=waist_cm, photo_url=photo_url,
        ))
        # Triggers nutrition recalibration via event handler wired in Sprint 2.
        await self.bus.publish(WeightLogged(user_id=user_id, weight_kg=weight_kg, at=now))


@dataclass(slots=True)
class GetWeightTrend:
    repo: SqlWeightLogRepository

    async def __call__(
        self, *, user_id: UUID, window_days: int = 30,
    ) -> list[tuple[datetime, float]]:
        return await self.repo.trend(user_id, window_days=window_days)
