"""Notification event handlers — fire-and-forget push on key domain events.

Subscribed events (all event-driven, zero cron — REGLA #3):
  FoodPhotoLogged  → "Almuerzo registrado. Faltan X kcal para tu meta de hoy."
  DayCompleted     → "Día completo 🎯 — racha de N días."

Handlers are best-effort (OK1 boundary): a notification failure MUST NOT
propagate and kill the originating use case.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.notifications.application.send_notification import SendNotification
from app.notifications.infrastructure.fcm_client import FcmClient
from app.plan.domain.events import DayCompleted
from app.vision.domain.events import FoodPhotoLogged

log = get_logger("notifications.handlers")


async def _kcal_remaining(session: AsyncSession, user_id: UUID) -> int | None:
    """Return remaining kcal for today (target_mid - logged). None if no targets."""
    row = (
        await session.execute(
            text(
                """
                SELECT (g.kcal_min + g.kcal_max) / 2 AS target,
                       COALESCE(SUM(fl.kcal), 0)::int AS logged
                  FROM nutritional_goals g
                  LEFT JOIN food_logs fl
                    ON fl.user_id = g.user_id AND fl.date = CURRENT_DATE
                 WHERE g.user_id = :uid
                 ORDER BY g.valid_from DESC
                 LIMIT 1
            """
            ),
            {"uid": str(user_id)},
        )
    ).mappings().first()
    if not row or not row["target"]:
        return None
    remaining = int(row["target"]) - int(row["logged"] or 0)
    return max(remaining, 0)


def make_food_photo_logged_handler(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[[FoodPhotoLogged], Coroutine[Any, Any, None]]:
    async def handle(event: FoodPhotoLogged) -> None:
        try:
            async with sessionmaker() as session:
                remaining = await _kcal_remaining(session, event.user_id)
                if remaining is None:
                    return
                if remaining > 0:
                    body_es = f"Foto registrada. Faltan ~{remaining} kcal para tu meta de hoy."
                    body_en = f"Photo logged. ~{remaining} kcal left for today's goal."
                else:
                    body_es = "¡Meta calórica de hoy alcanzada!"
                    body_en = "Today's calorie goal reached!"
                payload = {
                    "title_es": "Nova Nutrición",
                    "title_en": "Nova Nutrition",
                    "body_es": body_es,
                    "body_en": body_en,
                    "type": "food_photo_logged",
                }
                sender = SendNotification(session=session, fcm=FcmClient())
                await sender(user_id=event.user_id, payload=payload)
                await session.commit()
        except Exception as exc:  # noqa: BLE001  OK1: handler boundary, must not propagate
            log.warning("notifications.food_photo_logged.failed", err=str(exc)[:120])

    return handle


def make_day_completed_handler(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[[DayCompleted], Coroutine[Any, Any, None]]:
    async def handle(event: DayCompleted) -> None:
        try:
            async with sessionmaker() as session:
                streak_row = (
                    await session.execute(
                        text(
                            """
                            SELECT streak FROM streaks
                             WHERE user_id = :uid AND streak_type = 'daily'
                        """
                        ),
                        {"uid": str(event.user_id)},
                    )
                ).mappings().first()
                streak = int(streak_row["streak"]) if streak_row else 1

                payload = {
                    "title_es": "¡Día completo!",
                    "title_en": "Day complete!",
                    "body_es": f"Completaste tu plan de hoy. Racha: {streak} días.",
                    "body_en": f"You completed today's plan. Streak: {streak} days.",
                    "type": "day_completed",
                    "streak": streak,
                }
                sender = SendNotification(session=session, fcm=FcmClient())
                await sender(user_id=event.user_id, payload=payload)
                await session.commit()
        except Exception as exc:  # noqa: BLE001  OK1: handler boundary, must not propagate
            log.warning("notifications.day_completed.failed", err=str(exc)[:120])

    return handle


def register(bus: EventBus, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    bus.subscribe(FoodPhotoLogged, make_food_photo_logged_handler(sessionmaker))
    bus.subscribe(DayCompleted, make_day_completed_handler(sessionmaker))
