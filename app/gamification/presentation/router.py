"""Gamification REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.core.cache_keys import CacheKeys
from app.core.redis import get_redis
from app.gamification.application.use_cases import (
    GetAchievementsCatalog,
    GetLeaderboard,
    GetLevel,
    GetPendingCelebrations,
    GetUserProgress,
)
from app.gamification.infrastructure.repository import SqlGamificationRepository
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep

router = APIRouter(prefix="/gamification", tags=["gamification"])


class StreakOut(BaseModel):
    type: str
    value: int
    last_day: str | None
    longest_streak: int = 0
    total_days_logged: int = 0
    logged_today: bool = False


class StreaksResponse(BaseModel):
    streaks: list[StreakOut]


class AchievementsResponse(BaseModel):
    items: list[dict]


class LevelResponse(BaseModel):
    level: int | None = None
    xp: int | None = None
    xp_next: int | None = None
    title: str | None = None


class ProgressResponse(BaseModel):
    streak: int | None = None
    xp: int | None = None
    level: int | None = None
    achievements_count: int | None = None


class LeaderboardResponse(BaseModel):
    enabled: bool
    rows: list[dict]
    reason: str | None = None


class CelebrationsResponse(BaseModel):
    items: list[dict]


@router.get("/streak", response_model=StreakOut)
async def get_streak(current_user: CurrentUserDep, session: SessionDep) -> StreakOut:
    from app.gamification.domain.entities import StreakType

    repo = SqlGamificationRepository(session)
    s = await repo.streak(user_id=current_user, type_=StreakType.DAILY)

    stats = (
        await session.execute(
            text("""
                WITH daily AS (
                    SELECT DISTINCT date AS d
                    FROM food_logs
                    WHERE user_id = :uid
                      AND date >= CURRENT_DATE - INTERVAL '365 days'
                ),
                grp AS (
                    SELECT d,
                           d - (ROW_NUMBER() OVER (ORDER BY d) * INTERVAL '1 day') AS bucket
                    FROM daily
                ),
                runs AS (
                    SELECT COUNT(*) AS len FROM grp GROUP BY bucket
                )
                SELECT
                    COALESCE(MAX(len), 0)            AS longest,
                    (SELECT COUNT(*) FROM daily)     AS total,
                    EXISTS(
                        SELECT 1 FROM food_logs
                        WHERE user_id = :uid
                          AND date = CURRENT_DATE
                    ) AS logged_today
                FROM runs
            """),
            {"uid": current_user},
        )
    ).one_or_none()

    longest = int(stats.longest) if stats and stats.longest else 0
    total = int(stats.total) if stats and stats.total else 0
    logged_today = bool(stats.logged_today) if stats else False

    if not s:
        return StreakOut(
            type="daily",
            value=0,
            last_day=None,
            longest_streak=longest,
            total_days_logged=total,
            logged_today=logged_today,
        )
    return StreakOut(
        type=s.type.value,
        value=s.value,
        last_day=s.last_day.isoformat() if s.last_day else None,
        longest_streak=longest,
        total_days_logged=total,
        logged_today=logged_today,
    )


@router.get("/streaks", response_model=StreaksResponse)
async def get_streaks(current_user: CurrentUserDep, session: SessionDep) -> StreaksResponse:
    repo = SqlGamificationRepository(session)
    rows = await repo.streaks_for(current_user)
    return StreaksResponse(
        streaks=[
            StreakOut(
                type=s.type.value,
                value=s.value,
                last_day=s.last_day.isoformat() if s.last_day else None,
            )
            for s in rows
        ]
    )


@router.get("/achievements", response_model=AchievementsResponse)
async def list_achievements(current_user: CurrentUserDep, session: SessionDep) -> AchievementsResponse:
    uc = GetAchievementsCatalog(repo=SqlGamificationRepository(session))
    return AchievementsResponse(items=await uc(current_user))


@router.get("/level", response_model=LevelResponse)
async def get_level(current_user: CurrentUserDep, session: SessionDep) -> LevelResponse:
    uc = GetLevel(repo=SqlGamificationRepository(session))
    result = await uc(current_user)
    return LevelResponse(**result) if isinstance(result, dict) else result


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(current_user: CurrentUserDep, session: SessionDep) -> ProgressResponse:
    uc = GetUserProgress(repo=SqlGamificationRepository(session))
    result = await uc(current_user)
    return ProgressResponse(**result) if isinstance(result, dict) else result


_FF_LEADERBOARD_CACHE_KEY = CacheKeys.FF_LEADERBOARD
_FF_CACHE_TTL = 30  # seconds — flags change rarely; 30s lag is acceptable


async def _get_leaderboard_flags(session: SessionDep) -> dict[str, bool]:
    """Feature flags for the leaderboard endpoint, Redis-cached (30 s TTL).

    Cold-start / cache miss: single indexed DB read (ix_feature_flags_key).
    Warm: pure Redis GET — zero DB round-trips.
    """
    import json

    redis = get_redis()
    try:
        raw = await redis.get(_FF_LEADERBOARD_CACHE_KEY)
        if raw is not None:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass

    rows = (
        await session.execute(
            text(
                "SELECT key, enabled FROM feature_flags"
                " WHERE key IN ('leaderboard_enabled', 'leaderboard_l1_caps_enabled')"
            )
        )
    ).all()
    flags = {k: bool(e) for k, e in rows}
    try:
        await redis.set(_FF_LEADERBOARD_CACHE_KEY, json.dumps(flags), ex=_FF_CACHE_TTL)
    except Exception:  # noqa: BLE001
        pass
    return flags


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    current_user: CurrentUserDep,  # noqa: ARG001
    session: SessionDep,
    country: str = Query(default="us", min_length=2, max_length=2),
    period: str = Query(default="week"),
    limit: int = Query(default=20, ge=1, le=100),
) -> LeaderboardResponse:
    # Feature flag gate. ADR-0026 — two stages: the master flag
    # (`leaderboard_enabled`) controls the endpoint as a whole; the
    # sub-flag (`leaderboard_l1_caps_enabled`) confirms the L1 anti-cheat
    # caps have completed the 7-gate rollout. Master ON + sub-flag OFF
    # surfaces explicit `reason` so the client can render an empty state.
    flags = await _get_leaderboard_flags(session)
    if not flags.get("leaderboard_enabled"):
        return LeaderboardResponse(enabled=False, rows=[])
    if not flags.get("leaderboard_l1_caps_enabled"):
        return LeaderboardResponse(enabled=False, rows=[], reason="l1_caps_pending_validation")
    uc = GetLeaderboard(redis=get_redis())
    return LeaderboardResponse(enabled=True, rows=await uc(country=country, period=period, limit=limit))


@router.get("/celebrations/pending", response_model=CelebrationsResponse)
async def pending_celebrations(current_user: CurrentUserDep) -> CelebrationsResponse:
    uc = GetPendingCelebrations(redis=get_redis())
    return CelebrationsResponse(items=await uc(current_user))
