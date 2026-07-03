"""Single nightly maintenance cron — runs once daily at 03:00 UTC.

Replaces 6 separate crons that previously ran independently:
  - cleanup_idempotency_keys_cron   (was nightly 03:30)
  - leaderboard_audit_purge_cron    (was nightly 03:00)
  - cleanup_expired_otp_lockouts    (was every 5 min — overkill)
  - cleanup_expired_sse_tickets     (was every 5 min — overkill)
  - anomaly_score_task              (was daily 07:00)
  - coach_weekly_review_cron        (was hourly Sunday check — wasteful)
  - coach_recipe_story_backfill     (was daily 03:00)

All pure maintenance — no user-facing latency, safe to run sequentially.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.coach.application.features import recipe_story_backfill, weekly_review
from app.coach.infrastructure.sse_ticket import cleanup_expired
from app.core.db import session_scope
from app.core.logging import get_logger
from worker.anomaly_score_task import _run_anomaly_scoring  # type: ignore[attr-defined]

log = get_logger("worker.nightly_maintenance")

_RETENTION_DAYS = 180


async def nightly_maintenance_cron(ctx: dict[str, Any]) -> dict[str, Any]:
    """Single entry point for all nightly housekeeping."""
    results: dict[str, Any] = {}
    now_utc = datetime.now(UTC)
    is_sunday = now_utc.weekday() == 6

    # 1. Idempotency keys — delete expired
    async with session_scope() as session:
        res = await session.execute(
            text("DELETE FROM idempotency_keys WHERE expires_at < now()")
        )
        await session.commit()
        results["idempotency_keys_deleted"] = res.rowcount or 0

    # 2. Leaderboard + region audit + shadow ban — 180d retention (GDPR/LGPD)
    async with session_scope() as session:
        r1 = await session.execute(text(
            f"DELETE FROM leaderboard_audit WHERE created_at < now() - interval '{_RETENTION_DAYS} days'"  # noqa: S608
        ))
        r2 = await session.execute(text(
            f"DELETE FROM profile_region_change_audit WHERE changed_at < now() - interval '{_RETENTION_DAYS} days'"  # noqa: S608
        ))
        r3 = await session.execute(text(
            f"DELETE FROM gamification_shadow_ban WHERE lifted_at IS NOT NULL AND lifted_at < now() - interval '{_RETENTION_DAYS} days'"  # noqa: S608
        ))
        await session.commit()
        results["leaderboard_audit_deleted"] = r1.rowcount or 0
        results["region_audit_deleted"] = r2.rowcount or 0
        results["shadow_ban_deleted"] = r3.rowcount or 0

    # 3. OTP lockouts — reset expired
    async with session_scope() as session:
        res = await session.execute(text(
            "UPDATE otp_codes SET locked_until = NULL, attempts = 0"
            " WHERE locked_until IS NOT NULL AND locked_until < now()"
        ))
        await session.commit()
        results["otp_lockouts_reset"] = res.rowcount or 0

    # 4. SSE tickets — delete expired
    async with session_scope() as session:
        n = await cleanup_expired(session)
        results["sse_tickets_deleted"] = n

    # 5. Recipe story backfill — generate missing AI stories for recipes
    async with session_scope() as session:
        n = await recipe_story_backfill(session, batch=20)
        results["recipe_stories_written"] = n

    # 6. Anomaly scoring — detect gamification abuse (active users last 7d)
    try:
        anomaly_results = await _run_anomaly_scoring()
        results.update(anomaly_results)
    except Exception as exc:  # noqa: BLE001
        log.warning("nightly.anomaly_score.failed", err=str(exc))

    # 7. Weekly coach review — only on Sundays
    if is_sunday:
        reviewed = 0
        async with session_scope() as session:
            rows = (await session.execute(text(
                "SELECT user_id::text FROM user_profiles WHERE onboarding_completed = true"
            ))).scalars().all()
        for uid in rows:
            try:
                async with session_scope() as session:
                    await weekly_review(session, user_id=UUID(uid))
                reviewed += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("nightly.weekly_review.fail", uid=uid[:8], err=str(exc))
        results["weekly_reviews_sent"] = reviewed

    log.info("nightly_maintenance.done", **results, is_sunday=is_sunday)
    return results
