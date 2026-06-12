"""Sprint 6.C — gamification event handlers (Sprint 7 will broaden).

Subscribed events:
  - FoodLogged / FoodPhotoLogged  → maybe mark daily_goals[meal_time]
  - WaterLogged                   → maybe mark daily_goals.water + streak.daily
  - VisionJobCompleted            → no-op (food log handlers do the work)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.gamification.domain.events import CelebrationTriggered, DayCompleted
from app.gamification.infrastructure.anti_cheat_caps import (
    XP_DAILY_CAP,
    XP_PHOTO_CAP,
    XP_TEXT_CAP,
    XP_WEIGHT_CAP,
    check_and_increment_xp_daily,
    check_and_mark_sha_used,
    is_xp_cap_exceeded,
)
from app.shared.domain.time import utc_today
from app.tracking.domain.events import FoodLogged, WaterLogged, WeightLogged
from app.tracking.domain.fasting import FastingCompleted
from app.vision.domain.events import FoodPhotoLogged

log = get_logger("gamification.handlers")

# ADR-0026 L1 — streak 20h minimum interval. Redis key holds the ISO
# timestamp of the last streak-eligible log per (user, streak_type).
_STREAK_MIN_INTERVAL = timedelta(hours=20)
_STREAK_LAST_LOG_TTL_S = 60 * 60 * 48  # 48h covers any legit interval.


def _streak_last_log_key(user_id: UUID, stype: str) -> str:
    return f"streak:lastlog:{user_id}:{stype}"


async def _streak_interval_ok(user_id: UUID, stype: str) -> bool:
    """ADR-0026 — kill the 23:59→00:01 boundary-farming pattern.

    True ⇒ ≥20h since previous streak-eligible log (or first ever).
    Updates the marker on success so the next call sees the new time.
    """
    redis = get_redis()
    key = _streak_last_log_key(user_id, stype)
    now = datetime.now(UTC)
    raw = await redis.get(key)
    if raw:
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            last = None
        if last is not None and (now - last) < _STREAK_MIN_INTERVAL:
            log.info(
                "gamification.streak_interval_blocked",
                extra={
                    "user_id": str(user_id),
                    "stype": stype,
                    "elapsed_s": (now - last).total_seconds(),
                },
            )
            return False
    await redis.set(key, now.isoformat(), ex=_STREAK_LAST_LOG_TTL_S)
    return True


async def _award_xp_capped(  # noqa: PLR0913 — keyword-only audit args
    session: AsyncSession,
    *,
    user_id: UUID,
    action: str,
    xp_delta: int,
    source: str,
    bucket: str,
    bucket_cap: int,
    idempotency_key: str | None = None,
) -> bool:
    """ADR-0026 L1 — gate XP through Redis caps + write audit row.

    Returns True if XP was actually credited, False if a cap silently
    suppressed it. Caller is responsible for any side-effect tied to
    the award (e.g. ZADD into the leaderboard sorted set).

    Side effects:
      - Redis INCR on `total` + per-bucket counter.
      - Postgres INSERT into `leaderboard_audit` (idempotent via
        UNIQUE idempotency_key).
      - Structured log on cap suppression (`gamification.xp_capped`).
    """
    if xp_delta <= 0:
        return False
    redis = get_redis()
    today = datetime.now(UTC).date()

    bucket_value = await check_and_increment_xp_daily(
        redis, user_id, today, bucket, xp_delta
    )
    if is_xp_cap_exceeded(bucket_value, bucket_cap):
        log.warning(
            "gamification.xp_capped",
            extra={
                "user_id": str(user_id),
                "bucket": bucket,
                "value": bucket_value,
                "cap": bucket_cap,
                "action": action,
            },
        )
        return False
    total_value = await check_and_increment_xp_daily(
        redis, user_id, today, "total", xp_delta
    )
    if is_xp_cap_exceeded(total_value, XP_DAILY_CAP):
        log.warning(
            "gamification.xp_capped",
            extra={
                "user_id": str(user_id),
                "bucket": "total",
                "value": total_value,
                "cap": XP_DAILY_CAP,
                "action": action,
            },
        )
        return False

    idem = idempotency_key or f"{user_id}:{action}:{uuid4()}"
    await session.execute(
        text(
            """
            INSERT INTO leaderboard_audit
                (user_id, action, xp_delta, source, idempotency_key)
            VALUES (:uid, :action, :delta, :source, :idem)
            ON CONFLICT (idempotency_key) DO NOTHING
            """
        ),
        {
            "uid": str(user_id),
            "action": action,
            "delta": int(xp_delta),
            "source": source,
            "idem": idem,
        },
    )
    return True


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
        {"uid": str(user_id), "d": utc_today(), "item": item},
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
            {"uid": str(user_id), "d": utc_today()},
        )
    ).first()
    if not row:
        return False
    return int(row[0]) > 0 and int(row[0]) == int(row[1])


async def _bump_streak(session, *, user_id: UUID, stype: str) -> int:
    """Append +1 to streak.daily / .fasting / .protein, cap at last_day=yesterday.

    ADR-0026 L1 — refuses to bump when the previous streak-eligible
    log for this (user, stype) was <20h ago. Returns the current value
    unchanged in that case so callers do not fire celebrations on a
    boundary-farming pattern.
    """
    if not await _streak_interval_ok(user_id, stype):
        existing = (
            await session.execute(
                text(
                    "SELECT value FROM streaks WHERE user_id = :uid AND type = :t"
                ),
                {"uid": str(user_id), "t": stype},
            )
        ).scalar()
        return int(existing or 0)
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
        {"uid": str(user_id), "t": stype, "d": utc_today()},
    )
    val = res.scalar() or 1
    return int(val)


def register(bus: EventBus) -> None:  # noqa: PLR0915 — closure-heavy registry
    async def _on_food_logged(evt: FoodLogged) -> None:
        async with session_scope() as session:
            await _mark_daily_goal(session, user_id=evt.user_id, item=evt.meal_time)
            # ADR-0026 L1 — gate text-quick-log XP behind daily caps.
            await _award_xp_capped(
                session,
                user_id=evt.user_id,
                action="food_logged",
                xp_delta=10,
                source="text",
                bucket="text",
                bucket_cap=XP_TEXT_CAP,
            )
            if await _check_day_complete(session, user_id=evt.user_id):
                val = await _bump_streak(session, user_id=evt.user_id, stype="daily")
                await bus.publish(
                    DayCompleted(
                        user_id=evt.user_id,
                        on_date=utc_today(),
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
            # ADR-0026 L1 — same-SHA suppression. Look up the user's most
            # recent completed vision job (within 10 min of the event) and
            # award photo XP only when this SHA has not been seen in 24h.
            sha = (
                await session.execute(
                    text(
                        """
                        SELECT image_sha256 FROM vision_jobs
                         WHERE user_id = :uid
                           AND status = 'completed'
                           AND image_sha256 IS NOT NULL
                           AND created_at >= now() - interval '10 minutes'
                         ORDER BY created_at DESC
                         LIMIT 1
                        """
                    ),
                    {"uid": str(evt.user_id)},
                )
            ).scalar()
            redis = get_redis()
            first_use = True
            if sha:
                first_use = await check_and_mark_sha_used(
                    redis, evt.user_id, str(sha)
                )
            if not first_use:
                log.info(
                    "gamification.photo_xp_suppressed_same_sha",
                    extra={"user_id": str(evt.user_id), "sha": str(sha)},
                )
                return
            await _award_xp_capped(
                session,
                user_id=evt.user_id,
                action="photo_logged",
                xp_delta=25,
                source="photo",
                bucket="photo",
                bucket_cap=XP_PHOTO_CAP,
            )

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
                        {"uid": str(evt.user_id), "d": utc_today()},
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

    async def _on_weight_logged(evt: WeightLogged) -> None:
        # ADR-0026 L1 — weight XP gated. No domain side-effect beyond
        # the cap counter + audit row; legacy gamification has no
        # weight-specific badge today.
        async with session_scope() as session:
            await _award_xp_capped(
                session,
                user_id=evt.user_id,
                action="weight_logged",
                xp_delta=5,
                source="weight",
                bucket="weight",
                bucket_cap=XP_WEIGHT_CAP,
            )

    bus.subscribe(FoodLogged, _on_food_logged)
    bus.subscribe(FoodPhotoLogged, _on_photo_logged)
    bus.subscribe(WaterLogged, _on_water_logged)
    bus.subscribe(WeightLogged, _on_weight_logged)
    bus.subscribe(FastingCompleted, _on_fasting_completed)
    bus.subscribe(FoodLogged, _check_achievements_food)
    bus.subscribe(FastingCompleted, _check_achievements_fasting)
    bus.subscribe(DayCompleted, _check_achievements_day)
