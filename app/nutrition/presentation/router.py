"""Nutrition router: GET /me/targets, GET /me/targets/history, GET /me/weekly-summary."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Response

from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.nutrition.application.use_cases import (
    GetCurrentGoals,
    GetGoalsHistory,
    GetWeeklySummary,
)
from app.nutrition.domain.state_machine import NutritionalGoals
from app.nutrition.infrastructure.repositories import SqlNutritionalGoalsRepository
from app.nutrition.presentation.schemas import GoalsResponse, WeeklySummaryResponse

router = APIRouter(tags=["nutrition"])


def _to_resp(g: NutritionalGoals) -> GoalsResponse:
    return GoalsResponse(
        id=g.id,
        kcal_min=g.kcal_min,
        kcal_max=g.kcal_max,
        kcal_target=(g.kcal_min + g.kcal_max) // 2,
        protein_g=g.protein_g,
        carbs_g=g.carbs_g,
        fat_g=g.fat_g,
        water_ml=g.water_ml,
        bmr=g.bmr,
        tdee=g.tdee,
        activity_factor=g.activity_factor,
        reason=g.reason,
        valid_from=g.valid_from,
        valid_to=g.valid_to,
    )


@router.get("/me/targets", response_model=GoalsResponse)
async def get_targets(current_user: CurrentUserDep, session: SessionDep) -> GoalsResponse:
    uc = GetCurrentGoals(goals_repo=SqlNutritionalGoalsRepository(session))
    return _to_resp(await uc(user_id=current_user))


@router.get("/me/targets/history", response_model=list[GoalsResponse])
async def get_targets_history(
    current_user: CurrentUserDep,
    session: SessionDep,
    http_response: Response,
    limit: int = Query(default=20, ge=1, le=100, description="Max items to return"),
    cursor: Optional[datetime] = Query(
        default=None,
        description=(
            "Exclusive upper bound on valid_from (ISO-8601). "
            "Pass the value from the X-Next-Cursor response header to fetch the next page."
        ),
    ),
) -> list[GoalsResponse]:
    uc = GetGoalsHistory(goals_repo=SqlNutritionalGoalsRepository(session))
    items = await uc(user_id=current_user, limit=limit, cursor=cursor)
    result = [_to_resp(g) for g in items]
    # Emit next-page cursor when the page is full (there may be more rows).
    if len(result) == limit:
        http_response.headers["X-Next-Cursor"] = result[-1].valid_from.isoformat()
    return result


@router.get("/me/weekly-summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> WeeklySummaryResponse:
    uc = GetWeeklySummary(session=session)
    data = await uc(user_id=current_user)
    return WeeklySummaryResponse(**data)
