"""Gamification REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

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


@router.get("/streak")
async def get_streak(current_user: CurrentUserDep, session: SessionDep) -> dict:
    repo = SqlGamificationRepository(session)
    from app.gamification.domain.entities import StreakType

    s = await repo.streak(user_id=current_user, type_=StreakType.DAILY)
    if not s:
        return {"type": "daily", "value": 0, "last_day": None}
    return {
        "type": s.type.value,
        "value": s.value,
        "last_day": s.last_day.isoformat() if s.last_day else None,
    }


@router.get("/streaks")
async def get_streaks(current_user: CurrentUserDep, session: SessionDep) -> dict:
    repo = SqlGamificationRepository(session)
    rows = await repo.streaks_for(current_user)
    return {
        "streaks": [
            {
                "type": s.type.value,
                "value": s.value,
                "last_day": s.last_day.isoformat() if s.last_day else None,
            }
            for s in rows
        ]
    }


@router.get("/achievements")
async def list_achievements(current_user: CurrentUserDep, session: SessionDep) -> dict:
    uc = GetAchievementsCatalog(repo=SqlGamificationRepository(session))
    return {"items": await uc(current_user)}


@router.get("/level")
async def get_level(current_user: CurrentUserDep, session: SessionDep) -> dict:
    uc = GetLevel(repo=SqlGamificationRepository(session))
    return await uc(current_user)


@router.get("/progress")
async def get_progress(current_user: CurrentUserDep, session: SessionDep) -> dict:
    uc = GetUserProgress(repo=SqlGamificationRepository(session))
    return await uc(current_user)


@router.get("/leaderboard")
async def get_leaderboard(
    current_user: CurrentUserDep,  # noqa: ARG001
    session: SessionDep,  # noqa: ARG001
    country: str = Query(default="us", min_length=2, max_length=2),
    period: str = Query(default="week"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    # Feature flag gate. ADR-0026 — two stages: the master flag
    # (`leaderboard_enabled`) controls the endpoint as a whole; the
    # sub-flag (`leaderboard_l1_caps_enabled`) confirms the L1 anti-cheat
    # caps have completed the 7-gate rollout. Master ON + sub-flag OFF
    # surfaces explicit `reason` so the client can render an empty state.
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(
                """
                SELECT key, enabled FROM feature_flags
                 WHERE key IN ('leaderboard_enabled', 'leaderboard_l1_caps_enabled')
                """
            )
        )
    ).all()
    flags = {k: bool(e) for k, e in rows}
    if not flags.get("leaderboard_enabled"):
        return {"enabled": False, "rows": []}
    if not flags.get("leaderboard_l1_caps_enabled"):
        return {
            "enabled": False,
            "rows": [],
            "reason": "l1_caps_pending_validation",
        }
    uc = GetLeaderboard(redis=get_redis())
    return {"enabled": True, "rows": await uc(country=country, period=period, limit=limit)}


@router.get("/celebrations/pending")
async def pending_celebrations(current_user: CurrentUserDep) -> dict:
    uc = GetPendingCelebrations(redis=get_redis())
    return {"items": await uc(current_user)}
