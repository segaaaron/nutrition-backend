"""Tracking router — /logs/water, /logs/weight, /logs/weight/trend."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy import text

from app.core.event_bus import get_event_bus
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.tracking.application.use_cases import GetWeightTrend, LogWater, LogWeight
from app.tracking.infrastructure.repositories import (
    SqlWaterLogRepository,
    SqlWeightLogRepository,
)
from app.tracking.presentation.schemas import (
    LogWaterRequest,
    LogWaterResponse,
    LogWeightRequest,
    TrendPoint,
    WeightTrendResponse,
)

router = APIRouter(tags=["tracking"])


@router.post("/logs/water", response_model=LogWaterResponse, status_code=status.HTTP_201_CREATED)
async def log_water(
    body: LogWaterRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> LogWaterResponse:
    uc = LogWater(repo=SqlWaterLogRepository(session), bus=get_event_bus())
    total = await uc(user_id=current_user, ml=body.ml, at=body.at)
    return LogWaterResponse(total_today_ml=total)


@router.get("/logs/water/today", response_model=LogWaterResponse)
async def get_water_today(current_user: CurrentUserDep, session: SessionDep) -> LogWaterResponse:
    repo = SqlWaterLogRepository(session)
    total = await repo.total_today(current_user)
    goal_row = (
        await session.execute(
            text(
                """
                SELECT water_ml FROM nutritional_goals
                 WHERE user_id = :uid ORDER BY valid_from DESC LIMIT 1
            """
            ),
            {"uid": str(current_user)},
        )
    ).mappings().first()
    goal_ml = int(goal_row["water_ml"]) if goal_row and goal_row["water_ml"] else None
    return LogWaterResponse(total_today_ml=total, goal_ml=goal_ml)


@router.post("/logs/weight", status_code=status.HTTP_201_CREATED)
async def log_weight(
    body: LogWeightRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    uc = LogWeight(repo=SqlWeightLogRepository(session), bus=get_event_bus())
    await uc(
        user_id=current_user,
        weight_kg=body.weight_kg,
        body_fat_pct=body.body_fat_pct,
        waist_cm=body.waist_cm,
        photo_url=body.photo_url,
    )
    return {"ok": True}


@router.get("/logs/weight/trend", response_model=WeightTrendResponse)
async def get_weight_trend(
    current_user: CurrentUserDep,
    session: SessionDep,
    window: str = Query(default="30d", pattern=r"^\d{1,3}d$"),
) -> WeightTrendResponse:
    days = min(int(window.rstrip("d")), 365)
    uc = GetWeightTrend(repo=SqlWeightLogRepository(session))
    series = await uc(user_id=current_user, window_days=days)
    return WeightTrendResponse(
        window_days=days,
        points=[TrendPoint(t=t, value=v) for t, v in series],
    )
