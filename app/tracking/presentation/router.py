"""Tracking router — /logs/water, /logs/weight, /logs/weight/trend."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

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
    total = await uc(user_id=current_user, ml=body.ml)
    return LogWaterResponse(total_today_ml=total)


@router.get("/logs/water/today", response_model=LogWaterResponse)
async def get_water_today(current_user: CurrentUserDep, session: SessionDep) -> LogWaterResponse:
    repo = SqlWaterLogRepository(session)
    return LogWaterResponse(total_today_ml=await repo.total_today(current_user))


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
    window: str = Query(default="30d", pattern=r"^\d+d$"),
) -> WeightTrendResponse:
    days = int(window.rstrip("d"))
    uc = GetWeightTrend(repo=SqlWeightLogRepository(session))
    series = await uc(user_id=current_user, window_days=days)
    return WeightTrendResponse(
        window_days=days,
        points=[TrendPoint(t=t, value=v) for t, v in series],
    )
