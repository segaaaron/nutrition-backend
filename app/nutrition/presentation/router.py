"""Nutrition router: GET /me/targets, GET /me/targets/history."""

from __future__ import annotations

from fastapi import APIRouter

from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.nutrition.application.use_cases import (
    GetCurrentGoals,
    GetGoalsHistory,
)
from app.nutrition.domain.state_machine import NutritionalGoals
from app.nutrition.infrastructure.repositories import SqlNutritionalGoalsRepository
from app.nutrition.presentation.schemas import GoalsResponse

router = APIRouter(tags=["nutrition"])


def _to_resp(g: NutritionalGoals) -> GoalsResponse:
    return GoalsResponse(
        id=g.id,
        kcal_min=g.kcal_min,
        kcal_max=g.kcal_max,
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
) -> list[GoalsResponse]:
    uc = GetGoalsHistory(goals_repo=SqlNutritionalGoalsRepository(session))
    return [_to_resp(g) for g in await uc(user_id=current_user, limit=50)]
