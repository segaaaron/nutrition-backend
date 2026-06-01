"""Async tracking repos. Reads of the weight trend hit the Timescale
continuous aggregate (`biometric_aggregates_daily`) when possible to skip
chunk scans.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tracking.domain.entities import WaterLog, WeightLog
from app.tracking.infrastructure.models import WaterLogModel, WeightLogModel


class SqlWaterLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def append(self, log: WaterLog) -> None:
        self.s.add(WaterLogModel(
            time=log.time, user_id=log.user_id, ml=log.ml, target_ml=log.target_ml,
        ))
        await self.s.flush()

    async def total_today(self, user_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        sql = text("""
            SELECT COALESCE(SUM(ml), 0)::int
              FROM water_logs
             WHERE user_id = :uid AND time >= :start
        """)
        res = await self.s.execute(sql, {"uid": str(user_id), "start": day_start})
        row = res.first()
        return int(row[0]) if row else 0


class SqlWeightLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def append(self, log: WeightLog) -> None:
        self.s.add(WeightLogModel(
            time=log.time, user_id=log.user_id, weight_kg=log.weight_kg,
            body_fat_pct=log.body_fat_pct, waist_cm=log.waist_cm,
            photo_url=log.photo_url,
        ))
        await self.s.flush()

    async def latest(
        self, user_id: UUID,
    ) -> tuple[datetime, "Decimal"] | None:  # type: ignore[name-defined]
        """Returns (time, weight_kg) of most recent log, or None."""
        from decimal import Decimal
        sql = text("""
            SELECT time, weight_kg FROM weight_logs
             WHERE user_id = :uid
             ORDER BY time DESC LIMIT 1
        """)
        try:
            row = (await self.s.execute(sql, {"uid": str(user_id)})).first()
        except Exception:  # noqa: BLE001
            return None
        if row is None:
            return None
        return row[0], Decimal(str(row[1]))

    async def trend(
        self, user_id: UUID, *, window_days: int,
    ) -> list[tuple[datetime, float]]:
        # Prefer the continuous aggregate (daily means) — chunk scans are
        # avoided for the common 30/60/90-day dashboards.
        sql = text("""
            SELECT day, weight_kg_mean
              FROM biometric_aggregates_daily
             WHERE user_id = :uid
               AND day >= (CURRENT_DATE - (:days || ' days')::interval)
             ORDER BY day ASC
        """)
        try:
            res = await self.s.execute(sql, {"uid": str(user_id), "days": window_days})
            rows = list(res.all())
            if rows:
                return [(r[0], float(r[1])) for r in rows]
        except Exception:  # noqa: BLE001
            pass
        # Fallback raw scan (small dataset / pre-aggregate compute).
        sql2 = text("""
            SELECT time, weight_kg FROM weight_logs
             WHERE user_id = :uid
               AND time >= (now() - (:days || ' days')::interval)
             ORDER BY time ASC
        """)
        res2 = await self.s.execute(sql2, {"uid": str(user_id), "days": window_days})
        return [(r[0], float(r[1])) for r in res2.all()]
