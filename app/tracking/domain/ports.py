"""Tracking ports."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.tracking.domain.entities import WaterLog, WeightLog


class WaterLogRepository(Protocol):
    async def append(self, log: WaterLog) -> None: ...
    async def total_today(self, user_id: UUID) -> int: ...


class WeightLogRepository(Protocol):
    async def append(self, log: WeightLog) -> None: ...
    async def trend(
        self, user_id: UUID, *, window_days: int
    ) -> list[tuple[datetime, float]]: ...
