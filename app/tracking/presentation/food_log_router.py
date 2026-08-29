"""Food-log REST endpoints (Sprint 7.A).

Routes:
  - POST   /logs/food                  manual log (recipe or food)
  - GET    /logs/food                  paginated, filtered
  - DELETE /logs/food/{id}             soft-delete via audit_log
  - GET    /logs/food/totals/today
  - GET    /logs/food/totals/trend
  - GET    /logs/food/micros/today
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from app.core.errors import NotFoundError, ValidationError
from app.core.event_bus import get_event_bus
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.shared.domain.time import utc_today
from app.shared.i18n import LocaleDep
from app.tracking.application.food_log_uc import (
    DeleteFoodLog,
    GetDailyTotals,
    GetMacrosTrend,
    GetMicrosToday,
    QueryFoodLogs,
    _cache_key_totals,
)
from app.tracking.domain.food_log import FoodLogSearchQuery
from app.tracking.infrastructure.food_log_repository import SqlFoodLogRepository

router = APIRouter(tags=["tracking-food"])


class ManualFoodLogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: UUID | None = None
    food_id: UUID | None = None
    meal_time: Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"]
    servings: float = Field(default=1.0, gt=0, le=20)
    amount_g: float | None = Field(default=None, gt=0, le=5000)
    log_date: date | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "ManualFoodLogRequest":
        if (self.recipe_id is None) == (self.food_id is None):
            raise ValueError("provide exactly one of recipe_id or food_id")
        if self.food_id is not None and self.amount_g is None:
            raise ValueError("amount_g is required when logging a food item")
        return self


class ManualFoodLogResponse(BaseModel):
    food_log_id: UUID


@router.post("/logs/food", response_model=ManualFoodLogResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_food_log(
    body: ManualFoodLogRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ManualFoodLogResponse:
    """Log a recipe or food item manually (no photo required).

    recipe_id: log a full recipe scaled by servings.
    food_id:   log an individual food item; amount_g required.
    """
    log_date = body.log_date or utc_today()
    flog_id = uuid4()

    if body.recipe_id is not None:
        row = (
            await session.execute(
                text(
                    "SELECT kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg "
                    "FROM recipes WHERE id = :rid"
                ),
                {"rid": str(body.recipe_id)},
            )
        ).first()
        if row is None:
            raise NotFoundError("recipe_not_found")
        s = body.servings
        await session.execute(
            text(
                """
                INSERT INTO food_logs (
                    id, user_id, date, meal_time, recipe_id,
                    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g,
                    method, created_at
                ) VALUES (
                    :id, :uid, :d, :mt, :rid,
                    :kc, :pg, :cg, :fg, :fibg, :sug,
                    'manual', now()
                )
                """
            ),
            {
                "id": str(flog_id),
                "uid": str(current_user),
                "d": log_date,
                "mt": body.meal_time,
                "rid": str(body.recipe_id),
                "kc": round((row.kcal or 0) * s),
                "pg": round((row.protein_g or 0) * s),
                "cg": round((row.carbs_g or 0) * s),
                "fg": round((row.fat_g or 0) * s),
                "fibg": round((row.fiber_g or 0) * s),
                "sug": round((row.sugar_g or 0) * s),
            },
        )

    else:
        # food_id path — amount_g required (validated above)
        row = (
            await session.execute(
                text(
                    "SELECT kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, portion_g "
                    "FROM foods WHERE id = :fid"
                ),
                {"fid": str(body.food_id)},
            )
        ).first()
        if row is None:
            raise NotFoundError("food_not_found")
        portion = float(row.portion_g or 100) or 100.0
        ratio = body.amount_g / portion  # type: ignore[operator]
        await session.execute(
            text(
                """
                INSERT INTO food_logs (
                    id, user_id, date, meal_time, food_id, amount_g,
                    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g,
                    method, created_at
                ) VALUES (
                    :id, :uid, :d, :mt, :fid, :ag,
                    :kc, :pg, :cg, :fg, :fibg, :sug,
                    'manual', now()
                )
                """
            ),
            {
                "id": str(flog_id),
                "uid": str(current_user),
                "d": log_date,
                "mt": body.meal_time,
                "fid": str(body.food_id),
                "ag": body.amount_g,
                "kc": round((row.kcal or 0) * ratio),
                "pg": round((row.protein_g or 0) * ratio),
                "cg": round((row.carbs_g or 0) * ratio),
                "fg": round((row.fat_g or 0) * ratio),
                "fibg": round((row.fiber_g or 0) * ratio),
                "sug": round((row.sugar_g or 0) * ratio),
            },
        )

    await session.commit()
    await get_redis().delete(_cache_key_totals(current_user, log_date))
    return ManualFoodLogResponse(food_log_id=flog_id)


class FoodLogOut(BaseModel):
    id: UUID
    user_id: UUID
    date: date
    meal_time: str
    method: str
    food_id: UUID | None = None
    recipe_id: UUID | None = None
    free_text_name: str | None = None
    display_name: str | None = None  # resolved: food.name_es / recipe name / free_text_name
    amount_g: float | None = None
    kcal: int | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None
    confidence: float | None = None
    source_image_url: str | None = None
    created_at: datetime | None = None
    is_adjusted: bool = False


class FoodLogPage(BaseModel):
    items: list[FoodLogOut]
    next_cursor: str | None


@router.get("/logs/food", response_model=FoodLogPage)
async def query_food_logs(
    current_user: CurrentUserDep,
    session: SessionDep,
    locale: LocaleDep,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    meal_time: Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"] | None = Query(default=None),
    method: Literal["photo", "voice", "text", "barcode", "search", "manual", "plan"] | None = Query(
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

    # Batch-resolve display names for catalog logs (food_id / recipe_id).
    food_ids = [i.food_id for i in items if i.food_id]
    recipe_ids = [i.recipe_id for i in items if i.recipe_id]
    food_names: dict[UUID, str] = {}
    recipe_names: dict[UUID, str] = {}
    if food_ids:
        rows = (
            await session.execute(
                text("SELECT id, name_en, name_translations FROM foods WHERE id = ANY(:ids)"),
                {"ids": food_ids},
            )
        ).all()
        for row in rows:
            tr = row.name_translations or {}
            if locale == "en":
                food_names[row.id] = row.name_en or tr.get("es") or ""
            else:
                food_names[row.id] = tr.get(locale) or tr.get("es") or row.name_en or ""
    if recipe_ids:
        rows = (
            await session.execute(
                text("SELECT id, name_en, name_translations FROM recipes WHERE id = ANY(:ids)"),
                {"ids": recipe_ids},
            )
        ).all()
        for row in rows:
            tr = row.name_translations or {}
            if locale == "en":
                recipe_names[row.id] = row.name_en or tr.get("es") or ""
            else:
                recipe_names[row.id] = tr.get(locale) or tr.get("es") or row.name_en or ""

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
            display_name=(
                food_names.get(i.food_id)
                if i.food_id
                else recipe_names.get(i.recipe_id)
                if i.recipe_id
                else i.free_text_name
            ),
            amount_g=float(i.amount_g) if i.amount_g is not None else None,
            kcal=i.kcal,
            protein_g=i.protein_g,
            carbs_g=i.carbs_g,
            fat_g=i.fat_g,
            confidence=float(i.confidence) if i.confidence is not None else None,
            source_image_url=i.source_image_url,
            created_at=i.created_at,
            is_adjusted=i.is_adjusted,
        )
        for i in items
    ]
    return FoodLogPage(items=out, next_cursor=next_cursor)


class DeleteReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


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
    window: str = Query(default="30d", pattern=r"^\d{1,3}d$"),
) -> MacrosTrendOut:
    days = min(int(window.rstrip("d")), 365)
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
