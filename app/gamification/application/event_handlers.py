"""Sprint 6.C — gamification event handlers (Sprint 7 will broaden).

Subscribed events:
  - FoodLogged / FoodPhotoLogged  → maybe mark daily_goals[meal_time]
  - WaterLogged                   → maybe mark daily_goals.water + streak.daily
  - VisionJobCompleted            → no-op (food log handlers do the work)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import text

from app.core.db import session_scope
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.gamification.domain.events import CelebrationTriggered, DayCompleted
from app.tracking.domain.events import FoodLogged, WaterLogged
from app.vision.domain.events import FoodPhotoLogged

log = get_logger("gamification.handlers")


async def _mark_daily_goal(session, *, user_id: UUID, item: str) -> None:
    await session.execute(text("""
        INSERT INTO daily_goals (user_id, date, item, completed, completed_at)
        VALUES (:uid, :d, :item, true, now())
        ON CONFLICT (user_id, date, item) DO UPDATE SET
          completed = true, completed_at = now()
    """), {"uid": str(user_id), "d": date.today(), "item": item})


async def _check_day_complete(session, *, user_id: UUID) -> bool:
    row = (await session.execute(text("""
        SELECT COUNT(*) FILTER (WHERE completed = true) AS done,
               COUNT(*) AS total
          FROM daily_goals WHERE user_id = :uid AND date = :d
    """), {"uid": str(user_id), "d": date.today()})).first()
    if not row:
        return False
    return int(row[0]) > 0 and int(row[0]) == int(row[1])


async def _bump_streak(session, *, user_id: UUID, stype: str) -> int:
    """Append +1 to streak.daily / .fasting / .protein, cap at last_day=yesterday."""
    res = await session.execute(text("""
        INSERT INTO streaks (user_id, type, value, last_day)
        VALUES (:uid, :t, 1, :d)
        ON CONFLICT (user_id, type) DO UPDATE SET
          value = CASE
            WHEN streaks.last_day = :d THEN streaks.value
            WHEN streaks.last_day = :d - INTERVAL '1 day' THEN streaks.value + 1
            ELSE 1
          END,
          last_day = :d
        RETURNING value
    """), {"uid": str(user_id), "t": stype, "d": date.today()})
    val = res.scalar() or 1
    return int(val)


def register(bus: EventBus) -> None:
    async def _on_food_logged(evt: FoodLogged) -> None:
        async with session_scope() as session:
            await _mark_daily_goal(session, user_id=evt.user_id, item=evt.meal_time)
            if await _check_day_complete(session, user_id=evt.user_id):
                val = await _bump_streak(session, user_id=evt.user_id, stype="daily")
                await bus.publish(DayCompleted(
                    user_id=evt.user_id, on_date=date.today(),
                    at=datetime.now(timezone.utc),
                ))
                if val in (7, 14, 30, 60, 90):
                    await bus.publish(CelebrationTriggered(
                        user_id=evt.user_id, code=f"streak_{val}",
                        at=datetime.now(timezone.utc),
                    ))

    async def _on_photo_logged(evt: FoodPhotoLogged) -> None:
        async with session_scope() as session:
            await _mark_daily_goal(session, user_id=evt.user_id, item=evt.meal_time)

    async def _on_water_logged(evt: WaterLogged) -> None:
        async with session_scope() as session:
            # Mark water goal complete if user passed today's water_ml target.
            goal = (await session.execute(text("""
                SELECT water_ml FROM nutritional_goals
                 WHERE user_id = :uid AND valid_to IS NULL
            """), {"uid": str(evt.user_id)})).scalar()
            if not goal:
                return
            today_total = (await session.execute(text("""
                SELECT COALESCE(SUM(ml),0)::int FROM water_logs
                 WHERE user_id = :uid AND time::date = :d
            """), {"uid": str(evt.user_id), "d": date.today()})).scalar() or 0
            if int(today_total) >= int(goal):
                await _mark_daily_goal(session, user_id=evt.user_id, item="water")
                if await _check_day_complete(session, user_id=evt.user_id):
                    await _bump_streak(session, user_id=evt.user_id, stype="daily")

    bus.subscribe(FoodLogged, _on_food_logged)
    bus.subscribe(FoodPhotoLogged, _on_photo_logged)
    bus.subscribe(WaterLogged, _on_water_logged)
