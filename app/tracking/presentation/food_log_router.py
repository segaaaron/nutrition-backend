"""Food-log REST endpoints (Sprint 7.A).

Routes:
  - GET    /logs/food                  paginated, filtered
  - DELETE /logs/food/{id}             soft-delete via audit_log
  - GET    /logs/food/totals/today
  - GET    /logs/food/totals/trend
  - GET    /logs/food/micros/today
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Query, Response, status
from pydantic import BaseModel, ConfigDict

from app.core.event_bus import get_event_bus
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.tracking.application.food_log_uc import (
    DeleteFoodLog,
    GetDailyTotals,
    GetMacrosTrend,
    GetMicrosToday,
    QueryFoodLogs,
)
from app.tracking.domain.food_log import FoodLogSearchQuery
from app.tracking.infrastructure.food_log_repository import SqlFoodLogRepository

router = APIRouter(tags=["tracking-food"])


class FoodLogOut(BaseModel):
    id: UUID
    user_id: UUID
    date: date
    meal_time: str
    method: str
    food_id: UUID | None = None
    recipe_id: UUID | None = None
    free_text_name: str | None = None
    amount_g: float | None = None
    kcal: int | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None
    confidence: float | None = None
    source_image_url: str | None = None
    created_at: datetime | None = None


class FoodLogPage(BaseModel):
    items: list[FoodLogOut]
    next_cursor: str | None


@router.get("/logs/food", response_model=FoodLogPage)
async def query_food_logs(
    current_user: CurrentUserDep,
    session: SessionDep,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"] | None = Query(default=None),
    method: Literal["photo", "voice", "text", "barcode", "search", "manual"] | None = Query(
        default=None
    ),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> FoodLogPage:
    # BOLA OK: QueryFoodLogs passes user_id to FoodLogSearchQuery — repo filters by user_id.
    uc = QueryFoodLogs(repo=SqlFoodLogRepository(session))
    items, next_cursor = await uc(
        FoodLogSearchQuery(
            user_id=current_user,
            date_from=date_from,
            date_to=date_to,
            meal_time=meal_time,
            method=method,
            cursor=cursor,
            limit=limit,
        )
    )
    out = [
        FoodLogOut(
            id=i.id,
            user_id=i.user_id,
            date=i.date,
            meal_time=i.meal_time,
            method=i.method,
            food_id=i.food_id,
            recipe_id=i.recipe_id,
            free_text_name=i.free_text_name,
            amount_g=float(i.amount_g) if i.amount_g is not None else None,
            kcal=i.kcal,
            protein_g=i.protein_g,
            carbs_g=i.carbs_g,
            fat_g=i.fat_g,
            confidence=float(i.confidence) if i.confidence is not None else None,
            source_image_url=i.source_image_url,
            created_at=i.created_at,
        )
        for i in items
    ]
    return FoodLogPage(items=out, next_cursor=next_cursor)


class DeleteReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


@router.delete("/logs/food/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food_log(
    log_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    body: DeleteReason | None = Body(default=None),
) -> Response:
    # BOLA OK: DeleteFoodLog use case passes user_id to repo which filters
    # DELETE ... WHERE id = :id AND user_id = :uid — raises NotFoundError if mismatch.
    uc = DeleteFoodLog(
        repo=SqlFoodLogRepository(session),
        bus=get_event_bus(),
        redis=get_redis(),
    )
    await uc(user_id=current_user, log_id=log_id, reason=(body.reason if body else None))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class DailyTotalsOut(BaseModel):
    date: date
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    fiber_g: int
    sugar_g: int
    sodium_mg: int


@router.get("/logs/food/totals/today", response_model=DailyTotalsOut)
async def totals_today(current_user: CurrentUserDep, session: SessionDep) -> DailyTotalsOut:
    uc = GetDailyTotals(repo=SqlFoodLogRepository(session), redis=get_redis())
    t = await uc(user_id=current_user)
    return DailyTotalsOut(
        date=t.date,
        kcal=t.kcal,
        protein_g=t.protein_g,
        carbs_g=t.carbs_g,
        fat_g=t.fat_g,
        fiber_g=t.fiber_g,
        sugar_g=t.sugar_g,
        sodium_mg=t.sodium_mg,
    )


class MacrosTrendOut(BaseModel):
    window_days: int
    points: list[dict]
    rolling_avg: dict


@router.get("/logs/food/totals/trend", response_model=MacrosTrendOut)
async def totals_trend(
    current_user: CurrentUserDep,
    session: SessionDep,
    window: str = Query(default="30d", pattern=r"^\d+d$"),
) -> MacrosTrendOut:
    days = int(window.rstrip("d"))
    uc = GetMacrosTrend(repo=SqlFoodLogRepository(session))
    out = await uc(user_id=current_user, window_days=days)
    return MacrosTrendOut(**out)


class MicrosOut(BaseModel):
    totals: dict
    gaps: dict


@router.get("/logs/food/micros/today", response_model=MicrosOut)
async def micros_today(current_user: CurrentUserDep, session: SessionDep) -> MicrosOut:
    uc = GetMicrosToday(repo=SqlFoodLogRepository(session))
    return MicrosOut(**await uc(user_id=current_user))
