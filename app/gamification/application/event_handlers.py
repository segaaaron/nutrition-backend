"""Sprint 6.C — gamification event handlers (Sprint 7 will broaden).

Subscribed events:
  - FoodLogged / FoodPhotoLogged  → maybe mark daily_goals[meal_time]
  - WaterLogged                   → maybe mark daily_goals.water + streak.daily
  - VisionJobCompleted            → no-op (food log handlers do the work)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import text

from app.core.db import session_scope
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.gamification.domain.events import CelebrationTriggered, DayCompleted
from app.tracking.domain.events import FoodLogged, WaterLogged
from app.tracking.domain.fasting import FastingCompleted
from app.vision.domain.events import FoodPhotoLogged

log = get_logger("gamification.handlers")


async def _mark_daily_goal(session, *, user_id: UUID, item: str) -> None:
    await session.execute(
        text(
            """
        INSERT INTO daily_goals (user_id, date, item, completed, completed_at)
        VALUES (:uid, :d, :item, true, now())
        ON CONFLICT (user_id, date, item) DO UPDATE SET
          completed = true, completed_at = now()
    """
        ),
        {"uid": str(user_id), "d": date.today(), "item": item},
    )


async def _check_day_complete(session, *, user_id: UUID) -> bool:
    row = (
        await session.execute(
            text(
                """
        SELECT COUNT(*) FILTER (WHERE completed = true) AS done,
               COUNT(*) AS total
          FROM daily_goals WHERE user_id = :uid AND date = :d
    """
            ),
            {"uid": str(user_id), "d": date.today()},
        )
    ).first()
    if not row:
        return False
    return int(row[0]) > 0 and int(row[0]) == int(row[1])


async def _bump_streak(session, *, user_id: UUID, stype: str) -> int:
    """Append +1 to streak.daily / .fasting / .protein, cap at last_day=yesterday."""
    res = await session.execute(
        text(
            """
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
    """
        ),
        {"uid": str(user_id), "t": stype, "d": date.today()},
    )
    val = res.scalar() or 1
    return int(val)


def register(bus: EventBus) -> None:
    async def _on_food_logged(evt: FoodLogged) -> None:
        async with session_scope() as session:
            await _mark_daily_goal(session, user_id=evt.user_id, item=evt.meal_time)
            if await _check_day_complete(session, user_id=evt.user_id):
                val = await _bump_streak(session, user_id=evt.user_id, stype="daily")
                await bus.publish(
                    DayCompleted(
                        user_id=evt.user_id,
                        on_date=date.today(),
                        at=datetime.now(UTC),
                    )
                )
                if val in (7, 14, 30, 60, 90):
                    await bus.publish(
                        CelebrationTriggered(
                            user_id=evt.user_id,
                            code=f"streak_{val}",
                            at=datetime.now(UTC),
                        )
                    )

    async def _on_photo_logged(evt: FoodPhotoLogged) -> None:
        async with session_scope() as session:
            await _mark_daily_goal(session, user_id=evt.user_id, item=evt.meal_time)

    async def _on_water_logged(evt: WaterLogged) -> None:
        async with session_scope() as session:
            # Mark water goal complete if user passed today's water_ml target.
            goal = (
                await session.execute(
                    text(
                        """
                SELECT water_ml FROM nutritional_goals
                 WHERE user_id = :uid AND valid_to IS NULL
            """
                    ),
                    {"uid": str(evt.user_id)},
                )
            ).scalar()
            if not goal:
                return
            today_total = (
                (
                    await session.execute(
                        text(
                            """
                SELECT COALESCE(SUM(ml),0)::int FROM water_logs
                 WHERE user_id = :uid AND time::date = :d
            """
                        ),
                        {"uid": str(evt.user_id), "d": date.today()},
                    )
                ).scalar()
                or 0
            )
            if int(today_total) >= int(goal):
                await _mark_daily_goal(session, user_id=evt.user_id, item="water")
                if await _check_day_complete(session, user_id=evt.user_id):
                    await _bump_streak(session, user_id=evt.user_id, stype="daily")

    async def _on_fasting_completed(evt: FastingCompleted) -> None:
        async with session_scope() as session:
            if evt.achieved:
                val = await _bump_streak(session, user_id=evt.user_id, stype="fasting")
                if val in (3, 7, 14, 30, 60):
                    await bus.publish(
                        CelebrationTriggered(
                            user_id=evt.user_id,
                            code=f"fasting_streak_{val}",
                            at=datetime.now(UTC),
                        )
                    )

    # --- Achievement check (Sprint 7.D) ---
    from app.core.redis import get_redis
    from app.gamification.application.use_cases import maybe_unlock
    from app.gamification.domain.catalog import CATALOG
    from app.gamification.infrastructure.repository import SqlGamificationRepository

    async def _check_achievements_food(evt: FoodLogged) -> None:
        async with session_scope() as session:
            repo = SqlGamificationRepository(session)
            redis = get_redis()
            # first_meal_logged
            n_logs = (
                await session.execute(
                    text("SELECT COUNT(*) FROM food_logs WHERE user_id = :uid"),
                    {"uid": str(evt.user_id)},
                )
            ).scalar() or 0
            if int(n_logs) == 1:
                ach = next(a for a in CATALOG if a.code == "first_meal_logged")
                await maybe_unlock(repo, bus, redis, user_id=evt.user_id, achievement=ach)

    async def _check_achievements_fasting(evt: FastingCompleted) -> None:
        if not evt.achieved:
            return
        async with session_scope() as session:
            repo = SqlGamificationRepository(session)
            redis = get_redis()
            code = {16: "first_fasting_16h", 18: "first_fasting_18h", 20: "first_fasting_20h"}.get(
                evt.method_h
            )
            if code:
                ach = next((a for a in CATALOG if a.code == code), None)
                if ach:
                    await maybe_unlock(repo, bus, redis, user_id=evt.user_id, achievement=ach)
            # fasting streak 7
            v = (
                await session.execute(
                    text("SELECT value FROM streaks WHERE user_id = :uid AND type = 'fasting'"),
                    {"uid": str(evt.user_id)},
                )
            ).scalar() or 0
            if int(v) >= 7:
                ach = next(a for a in CATALOG if a.code == "fasting_streak_7d")
                await maybe_unlock(repo, bus, redis, user_id=evt.user_id, achievement=ach)

    async def _check_achievements_day(evt: DayCompleted) -> None:
        async with session_scope() as session:
            repo = SqlGamificationRepository(session)
            redis = get_redis()
            v = (
                await session.execute(
                    text("SELECT value FROM streaks WHERE user_id = :uid AND type = 'daily'"),
                    {"uid": str(evt.user_id)},
                )
            ).scalar() or 0
            v = int(v)
            for threshold, code in (
                (3, "streak_3d"),
                (7, "streak_7d"),
                (14, "streak_14d"),
                (30, "streak_30d"),
                (100, "streak_100d"),
            ):
                if v >= threshold:
                    ach = next(a for a in CATALOG if a.code == code)
                    await maybe_unlock(repo, bus, redis, user_id=evt.user_id, achievement=ach)

    bus.subscribe(FoodLogged, _on_food_logged)
    bus.subscribe(FoodPhotoLogged, _on_photo_logged)
    bus.subscribe(WaterLogged, _on_water_logged)
    bus.subscribe(FastingCompleted, _on_fasting_completed)
    bus.subscribe(FoodLogged, _check_achievements_food)
    bus.subscribe(FastingCompleted, _check_achievements_fasting)
    bus.subscribe(DayCompleted, _check_achievements_day)
