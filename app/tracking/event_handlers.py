"""Tracking event handlers — cache invalidation + coach triggers on food logs."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.core.db import session_scope
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.plan.domain.events import MealCompleted
from app.shared.domain.time import utc_today
from app.tracking.application.food_log_uc import _cache_key_totals
from app.tracking.domain.events import FoodLogged

_log = get_logger("tracking.event_handlers")


def register(bus: EventBus) -> None:
    async def _on_meal_completed(evt: MealCompleted) -> None:
        if evt.recipe_id is None:
            return
        try:
            async with session_scope() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO food_logs (
                            id, user_id, date, meal_time, recipe_id,
                            kcal, protein_g, carbs_g, fat_g, method, idempotency_key, created_at
                        ) VALUES (
                            :id, :uid, :d, :mt, :rid,
                            :kc, :pg, :cg, :fg, 'plan', :idem, now()
                        )
                        ON CONFLICT (user_id, idempotency_key)
                        WHERE idempotency_key IS NOT NULL
                        DO NOTHING
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "uid": str(evt.user_id),
                        "d": evt.at.date(),
                        "mt": evt.meal_time,
                        "rid": str(evt.recipe_id),
                        "kc": evt.kcal,
                        "pg": evt.protein_g,
                        "cg": evt.carbs_g,
                        "fg": evt.fat_g,
                        "idem": f"plan-meal:{evt.meal_id}",
                    },
                )
            await get_redis().delete(_cache_key_totals(evt.user_id, utc_today()))
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "tracking.meal_completed_log.fail",
                user_id=str(evt.user_id)[:8],
                meal_id=str(evt.meal_id),
                err=str(exc),
            )

    async def _on_food_logged(evt: FoodLogged) -> None:
        # 1. Invalidate daily totals cache
        try:
            await get_redis().delete(_cache_key_totals(evt.user_id, utc_today()))
        except Exception:  # noqa: BLE001,S110
            pass

        # 2. Coach: proactive deviation check — writes assistant message to
        #    coach_messages table. iOS reads it on next conversation open.
        #    Push delivery added when FCM is wired (token registered by iOS).
        try:
            from app.coach.application.features import proactive_deviation

            async with session_scope() as session:
                await proactive_deviation(session, user_id=evt.user_id)
        except Exception as exc:  # noqa: BLE001
            _log.warning("coach.proactive_deviation.fail", user_id=str(evt.user_id)[:8], err=str(exc))

        # 3. Coach: macro repair — only after dinner, when full day is known.
        #    Writes assistant message to coach_messages. Same delivery model.
        if evt.meal_time == "dinner":
            try:
                from app.coach.application.features import macro_repair

                async with session_scope() as session:
                    await macro_repair(session, user_id=evt.user_id)
            except Exception as exc:  # noqa: BLE001
                _log.warning("coach.macro_repair.fail", user_id=str(evt.user_id)[:8], err=str(exc))

    bus.subscribe(FoodLogged, _on_food_logged)
    bus.subscribe(MealCompleted, _on_meal_completed)
