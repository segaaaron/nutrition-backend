"""Arq cron + ad-hoc tasks for the coach.

Cron jobs (all registered with backoff + max_retries 3, dead-lettered):
  - coach_macro_repair_cron      : per user, 19:00 user-locale-time
  - coach_proactive_alert_cron   : per user, 18:00 user-locale-time
  - coach_weekly_review_cron     : Sundays 18:00 user-locale-time
  - coach_recipe_story_backfill  : nightly 03:00 UTC, batch 20 recipes
  - cleanup_expired_sse_tickets  : every 5 min
  - cleanup_expired_otp_lockouts : every 5 min

Locale-aware scheduling: the cron runs hourly UTC and inspects each user
profile's locale → UTC offset, only firing for users whose local clock is
within the target hour. Cheap query — no per-user job in the queue.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.coach.application.features import (
    macro_repair,
    proactive_deviation,
    recipe_story_backfill,
    weekly_review,
)
from app.coach.infrastructure.sse_ticket import cleanup_expired
from app.core.db import session_scope
from app.core.logging import get_logger
from app.notifications.application.send_notification import SendNotification
from app.notifications.infrastructure.fcm_client import FcmClient

log = get_logger("worker.coach")

# Cheap locale → UTC offset lookup (LatAm avg -5, EU +1, UK 0, US -6 avg).
LOCALE_OFFSETS = {"es": -5, "pt": -3, "en": -5, "fr": 1, "de": 1}


async def _users_for_local_hour(session, target_hour: int) -> list[str]:
    now_utc = datetime.now(timezone.utc)
    rows = (await session.execute(text("""
        SELECT user_id::text, locale FROM user_profiles WHERE onboarding_completed = true
    """))).all()
    out: list[str] = []
    for r in rows:
        offset = LOCALE_OFFSETS.get(r[1], 0)
        local_hour = (now_utc.hour + offset) % 24
        if local_hour == target_hour:
            out.append(r[0])
    return out


async def coach_macro_repair_cron(ctx: dict[str, Any]) -> dict[str, int]:
    async with session_scope() as session:
        uids = await _users_for_local_hour(session, target_hour=19)
        n = 0
        for uid in uids:
            try:
                from uuid import UUID
                await macro_repair(session, user_id=UUID(uid))
                n += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("macro_repair.fail", uid=uid[:8], err=str(exc))
        return {"users": n}


async def coach_proactive_alert_cron(ctx: dict[str, Any]) -> dict[str, int]:
    async with session_scope() as session:
        uids = await _users_for_local_hour(session, target_hour=18)
        sender = SendNotification(session, FcmClient())
        n = 0
        for uid in uids:
            try:
                from uuid import UUID
                payload = await proactive_deviation(session, user_id=UUID(uid))
                if payload:
                    await sender(user_id=UUID(uid), payload=payload)
                    n += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("proactive.fail", uid=uid[:8], err=str(exc))
        return {"alerted": n}


async def coach_weekly_review_cron(ctx: dict[str, Any]) -> dict[str, int]:
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() != 6:  # Sunday
        return {"skipped": 1}
    async with session_scope() as session:
        uids = await _users_for_local_hour(session, target_hour=18)
        n = 0
        for uid in uids:
            try:
                from uuid import UUID
                await weekly_review(session, user_id=UUID(uid))
                n += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("weekly.fail", uid=uid[:8], err=str(exc))
        return {"reviewed": n}


async def coach_recipe_story_backfill_cron(ctx: dict[str, Any]) -> dict[str, int]:
    async with session_scope() as session:
        n = await recipe_story_backfill(session, batch=20)
        return {"stories_written": n}


async def cleanup_expired_sse_tickets_cron(ctx: dict[str, Any]) -> dict[str, int]:
    async with session_scope() as session:
        n = await cleanup_expired(session)
        return {"deleted": n}


async def cleanup_expired_otp_lockouts_cron(ctx: dict[str, Any]) -> dict[str, int]:
    async with session_scope() as session:
        res = await session.execute(text("""
            UPDATE otp_codes SET locked_until = NULL, attempts = 0
             WHERE locked_until IS NOT NULL AND locked_until < now()
        """))
        return {"unlocked": res.rowcount or 0}
