"""Notification event handlers — fire-and-forget push on key domain events.

Subscribed events (all event-driven, zero cron — REGLA #3):
  FoodPhotoLogged   → "Foto registrada. Faltan X kcal para tu meta de hoy."
  DayCompleted      → "Día completo — racha de N días."
  AchievementUnlocked → celebratory push per achievement code (E4 H1)
  StreakBroken      → motivational push when streak >= 3 resets (E4 H2)

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
from app.gamification.domain.events import AchievementUnlocked, DayCompleted, StreakBroken
from app.notifications.application.send_notification import SendNotification
from app.notifications.infrastructure.fcm_client import FcmClient
from app.vision.domain.events import FoodPhotoLogged

log = get_logger("notifications.handlers")

# E4 H1 — achievement messages keyed by code (es, en).
_ACHIEVEMENT_MESSAGES: dict[str, tuple[str, str]] = {
    "streak_3d": ("¡Racha de 3 días! Sigue así.", "3-day streak! Keep it up."),
    "streak_7d": ("¡Una semana completa! Eres constante.", "A full week! You're consistent."),
    "streak_14d": ("14 días seguidos. Estás formando un hábito real.", "14 days straight. A real habit is forming."),
    "streak_30d": ("¡Un mes! Solo el 3% llega aquí.", "One month! Only 3% get here."),
    "streak_100d": ("100 días. Dedicación total.", "100 days. Total dedication."),
    "first_meal_logged": ("¡Primera comida registrada! Empezó tu camino.", "First meal logged! Your journey begins."),
    "first_fasting_16h": ("¡Primer ayuno de 16h completado!", "First 16h fast completed!"),
    "fasting_streak_7d": ("7 ayunos seguidos. Disciplina real.", "7 consecutive fasts. Real discipline."),
    "protein_goal_7d": ("7 días cumpliendo tu meta de proteína. Sigue.", "7 days hitting your protein goal. Keep going."),
}

_ACHIEVEMENT_TITLE_ES = "Nova Nutrición"
_ACHIEVEMENT_TITLE_EN = "Nova Nutrition"


def _achievement_body(code: str, points: int) -> tuple[str, str]:
    if code in _ACHIEVEMENT_MESSAGES:
        return _ACHIEVEMENT_MESSAGES[code]
    return (
        f"¡Nuevo logro desbloqueado! +{points} pts",
        f"New achievement unlocked! +{points} pts",
    )


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
                # Columns: type (not streak_type), value (not streak) — schema 0001_init.
                streak_row = (
                    await session.execute(
                        text(
                            "SELECT value FROM streaks WHERE user_id = :uid AND type = 'daily'"
                        ),
                        {"uid": str(event.user_id)},
                    )
                ).scalar()
                streak = int(streak_row) if streak_row else 1

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


def make_achievement_unlocked_handler(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[[AchievementUnlocked], Coroutine[Any, Any, None]]:
    """E4 H1 — push when gamification unlocks an achievement."""

    async def handle(event: AchievementUnlocked) -> None:
        try:
            async with sessionmaker() as session:
                body_es, body_en = _achievement_body(event.code, event.points)
                payload = {
                    "title_es": _ACHIEVEMENT_TITLE_ES,
                    "title_en": _ACHIEVEMENT_TITLE_EN,
                    "body_es": body_es,
                    "body_en": body_en,
                    "type": "achievement_unlocked",
                    "code": event.code,
                    "points": event.points,
                }
                sender = SendNotification(session=session, fcm=FcmClient())
                await sender(user_id=event.user_id, payload=payload)
                await session.commit()
        except Exception as exc:  # noqa: BLE001  OK1: handler boundary, must not propagate
            log.warning("notifications.achievement_unlocked.failed", err=str(exc)[:120])

    return handle


def make_streak_broken_handler(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[[StreakBroken], Coroutine[Any, Any, None]]:
    """E4 H2 — push when a streak >= 3 resets. Motivational, not punitive."""

    async def handle(event: StreakBroken) -> None:
        if event.prev_value < 3:
            return  # short streaks not worth a push
        try:
            async with sessionmaker() as session:
                prev = event.prev_value
                if prev >= 30:
                    body_es = f"Racha de {prev} días rota. Eso fue real — puedes reconstruirlo."
                    body_en = f"{prev}-day streak ended. That was real — you can rebuild it."
                elif prev >= 7:
                    body_es = f"Tu racha de {prev} días terminó. Mañana es día 1 de la siguiente."
                    body_en = f"Your {prev}-day streak ended. Tomorrow is day 1 of the next one."
                else:
                    body_es = f"Perdiste tu racha de {prev} días. Puedes empezar de nuevo hoy."
                    body_en = f"Lost your {prev}-day streak. You can start fresh today."
                payload = {
                    "title_es": "Nova Nutrición",
                    "title_en": "Nova Nutrition",
                    "body_es": body_es,
                    "body_en": body_en,
                    "type": "streak_broken",
                    "prev_value": prev,
                }
                sender = SendNotification(session=session, fcm=FcmClient())
                await sender(user_id=event.user_id, payload=payload)
                await session.commit()
        except Exception as exc:  # noqa: BLE001  OK1: handler boundary, must not propagate
            log.warning("notifications.streak_broken.failed", err=str(exc)[:120])

    return handle


def register(bus: EventBus, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    bus.subscribe(FoodPhotoLogged, make_food_photo_logged_handler(sessionmaker))
    bus.subscribe(DayCompleted, make_day_completed_handler(sessionmaker))
    bus.subscribe(AchievementUnlocked, make_achievement_unlocked_handler(sessionmaker))
    bus.subscribe(StreakBroken, make_streak_broken_handler(sessionmaker))
