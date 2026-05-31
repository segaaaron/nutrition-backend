"""GET /goals/today + POST /goals/today/{item}/toggle.

Returns today's macro gap + 3 ranked snack suggestions filtered by the
missing macros (highest protein density first). Snack ranker reuses
Layer-3 style scoring deterministically — no LLM.
"""
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep

router = APIRouter(tags=["goals"])


class TodayGoalsResponse(BaseModel):
    kcal_goal: int
    kcal_consumed: int
    kcal_gap: int
    protein_goal: int
    protein_consumed: int
    protein_gap: int
    water_goal_ml: int
    water_consumed_ml: int
    daily_items: list[dict]
    snack_suggestions: list[dict]


@router.get("/goals/today", response_model=TodayGoalsResponse)
async def get_today(current_user: CurrentUserDep, session: SessionDep) -> TodayGoalsResponse:
    goal = (await session.execute(text("""
        SELECT kcal_min, kcal_max, protein_g, water_ml
          FROM nutritional_goals WHERE user_id = :uid AND valid_to IS NULL
    """), {"uid": str(current_user)})).first()
    if not goal:
        raise NotFoundError("nutritional_goals_missing")
    kcal_target = (int(goal[0]) + int(goal[1])) // 2

    intake = (await session.execute(text("""
        SELECT COALESCE(SUM(kcal),0)::int, COALESCE(SUM(protein_g),0)::int
          FROM food_logs WHERE user_id = :uid AND date = CURRENT_DATE
    """), {"uid": str(current_user)})).first()
    kcal_consumed = int(intake[0])
    protein_consumed = int(intake[1])
    kcal_gap = max(0, kcal_target - kcal_consumed)
    protein_gap = max(0, int(goal[2]) - protein_consumed)

    water_consumed = (await session.execute(text("""
        SELECT COALESCE(SUM(ml),0)::int FROM water_logs
         WHERE user_id = :uid AND time::date = CURRENT_DATE
    """), {"uid": str(current_user)})).scalar() or 0

    items = (await session.execute(text("""
        SELECT item, completed FROM daily_goals
         WHERE user_id = :uid AND date = CURRENT_DATE
    """), {"uid": str(current_user)})).all()

    # Snack ranking — protein per kcal, fits in gap.
    snacks_raw = []
    if kcal_gap >= 100 or protein_gap >= 5:
        snacks_raw = (await session.execute(text("""
            SELECT id::text, name_en, kcal, protein_g
              FROM recipes
             WHERE meal_time = 'snack' AND kcal IS NOT NULL AND kcal <= :kgap
             ORDER BY (CASE WHEN kcal>0 THEN protein_g::float / kcal ELSE 0 END) DESC
             LIMIT 3
        """), {"kgap": max(150, kcal_gap)})).all()

    return TodayGoalsResponse(
        kcal_goal=kcal_target, kcal_consumed=kcal_consumed, kcal_gap=kcal_gap,
        protein_goal=int(goal[2]), protein_consumed=protein_consumed,
        protein_gap=protein_gap,
        water_goal_ml=int(goal[3]), water_consumed_ml=int(water_consumed),
        daily_items=[{"item": r[0], "completed": r[1]} for r in items],
        snack_suggestions=[
            {"recipe_id": r[0], "name": r[1], "kcal": r[2], "protein_g": r[3]}
            for r in snacks_raw
        ],
    )


@router.post("/goals/today/{item}/toggle", status_code=status.HTTP_204_NO_CONTENT)
async def toggle_daily_item(
    item: Literal["breakfast", "lunch", "dinner", "water"],
    current_user: CurrentUserDep, session: SessionDep,
) -> None:
    await session.execute(text("""
        INSERT INTO daily_goals (user_id, date, item, completed, completed_at)
        VALUES (:uid, :d, :it, true, now())
        ON CONFLICT (user_id, date, item) DO UPDATE SET
          completed = NOT daily_goals.completed,
          completed_at = CASE WHEN NOT daily_goals.completed THEN now() ELSE NULL END
    """), {"uid": str(current_user), "d": date.today(), "it": item})
