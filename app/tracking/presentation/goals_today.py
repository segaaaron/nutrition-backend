"""GET /goals/today + POST /goals/today/{item}/toggle.

Returns today's macro gap + 3 ranked snack suggestions filtered by the
missing macros (highest protein density first). Snack ranker reuses
Layer-3 style scoring deterministically — no LLM.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.shared.domain.time import utc_today
from app.tracking.infrastructure.fasting_repository import SqlFastingRepository

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
    fasting: dict | None = None  # F4: fasting block — None when preference not set


@router.get("/goals/today", response_model=TodayGoalsResponse)
async def get_today(current_user: CurrentUserDep, session: SessionDep) -> TodayGoalsResponse:
    goal = (
        await session.execute(
            text(
                """
        SELECT kcal_min, kcal_max, protein_g, water_ml
          FROM nutritional_goals WHERE user_id = :uid AND valid_to IS NULL
    """
            ),
            {"uid": str(current_user)},
        )
    ).first()
    if not goal:
        raise NotFoundError("nutritional_goals_missing")
    kcal_target = (int(goal[0]) + int(goal[1])) // 2

    intake = (
        await session.execute(
            text(
                """
        SELECT COALESCE(SUM(kcal),0)::int, COALESCE(SUM(protein_g),0)::int
          FROM food_logs WHERE user_id = :uid AND date = CURRENT_DATE
    """
            ),
            {"uid": str(current_user)},
        )
    ).first()
    kcal_consumed = int(intake[0])
    protein_consumed = int(intake[1])
    kcal_gap = max(0, kcal_target - kcal_consumed)
    protein_gap = max(0, int(goal[2]) - protein_consumed)

    water_consumed = (
        (
            await session.execute(
                text(
                    """
        SELECT COALESCE(SUM(ml),0)::int FROM water_logs
         WHERE user_id = :uid AND time::date = CURRENT_DATE
    """
                ),
                {"uid": str(current_user)},
            )
        ).scalar()
        or 0
    )

    items = (
        await session.execute(
            text(
                """
        SELECT item, completed FROM daily_goals
         WHERE user_id = :uid AND date = CURRENT_DATE
    """
            ),
            {"uid": str(current_user)},
        )
    ).all()

    # Snack ranking — protein per kcal, fits in gap.
    snacks_raw = []
    if kcal_gap >= 100 or protein_gap >= 5:
        snacks_raw = (
            await session.execute(
                text(
                    """
            SELECT id::text, name_en, kcal, protein_g
              FROM recipes
             WHERE meal_time IN ('snack','morning_snack','afternoon_snack') AND kcal IS NOT NULL AND kcal <= :kgap
             ORDER BY (CASE WHEN kcal>0 THEN protein_g::float / kcal ELSE 0 END) DESC
             LIMIT 3
        """
                ),
                {"kgap": max(150, kcal_gap)},
            )
        ).all()

    # F4: Fasting block — resolve eligibility + state + streak.
    #
    # Starts ABSENT on purpose. The entire block runs inside a `try` whose
    # `except` swallows failures, so the init value is what ships on error.
    # `True` (fail-open) offered fasting to excluded users; `False` (fail-closed)
    # is worse — iOS treats an explicit `false` as a resolved decision and tears
    # the feature down for every device on the account.
    # Absent = "could not resolve; leave whatever the client had standing."
    # `false` must only mean the rule resolved to not-eligible.
    fasting_block: dict = {}
    try:
        from app.tracking.application.fasting_uc import (
            GetFastingActiveState,
            fasting_available_for,
        )
        fasting_repo = SqlFastingRepository(session)

        available = await fasting_available_for(session, current_user)
        fasting_block["available"] = available

        pref = await fasting_repo.get_preference(current_user)
        if pref and pref.enabled and available:
            state_uc = GetFastingActiveState(repo=fasting_repo)
            state_data = await state_uc(user_id=current_user)
            streak = await fasting_repo.streak_days(current_user)
            windows_7d = await fasting_repo.windows_completed_7d(current_user)
            fasting_block["state"] = state_data["state"]
            fasting_block["streak_days"] = streak
            fasting_block["windows_completed_7d"] = windows_7d
    except Exception:  # noqa: BLE001 — fasting block is additive; never break goals/today
        pass

    return TodayGoalsResponse(
        kcal_goal=kcal_target,
        kcal_consumed=kcal_consumed,
        kcal_gap=kcal_gap,
        protein_goal=int(goal[2]),
        protein_consumed=protein_consumed,
        protein_gap=protein_gap,
        water_goal_ml=int(goal[3]),
        water_consumed_ml=int(water_consumed),
        daily_items=[{"item": r[0], "completed": r[1]} for r in items],
        snack_suggestions=[
            {"recipe_id": r[0], "name": r[1], "kcal": r[2], "protein_g": r[3]} for r in snacks_raw
        ],
        fasting=fasting_block,
    )


@router.post("/goals/today/{item}/toggle", status_code=status.HTTP_204_NO_CONTENT)
async def toggle_daily_item(
    item: Literal["breakfast", "lunch", "dinner", "water"],
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    await session.execute(
        text(
            """
        INSERT INTO daily_goals (user_id, date, item, completed, completed_at)
        VALUES (:uid, :d, :it, true, now())
        ON CONFLICT (user_id, date, item) DO UPDATE SET
          completed = NOT daily_goals.completed,
          completed_at = CASE WHEN NOT daily_goals.completed THEN now() ELSE NULL END
    """
        ),
        {"uid": str(current_user), "d": utc_today(), "it": item},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
