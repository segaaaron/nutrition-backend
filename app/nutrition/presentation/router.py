"""Nutrition router: GET /me/targets, GET /me/targets/history, GET /me/weekly-summary."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Response

from app.core.logging import get_logger
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.nutrition.application.use_cases import (
    GetCurrentGoals,
    GetGoalsHistory,
    GetWeeklySummary,
    GetWeightInsights,
    GetWeightProgress,
)
from app.nutrition.domain.ideal_weight import WeightInsights
from app.nutrition.domain.state_machine import NutritionalGoals
from app.nutrition.infrastructure.repositories import (
    SqlNutritionalGoalsRepository,
    SqlProfileReader,
    SqlTrackingReader,
)
from app.nutrition.presentation.schemas import (
    GoalsResponse,
    WeeklySummaryResponse,
    WeightInsightsOut,
    WeightProgressResponse,
)

router = APIRouter(tags=["nutrition"])
_log = get_logger("nutrition.router")


def _weight_insights_out(
    wi: WeightInsights | None,
    *,
    kcal_target: int | None = None,
    tdee: int | None = None,
) -> WeightInsightsOut | None:
    if wi is None:
        return None
    projected: float | None = None
    if (
        kcal_target is not None
        and tdee is not None
        and wi.weight_gap_direction != "maintain"
    ):
        from app.nutrition.domain.weight_projection import expected_weekly_change
        proj = expected_weekly_change(kcal_target=kcal_target, tdee=tdee)
        projected = float(proj.weekly_kg)

    # Recompute ETA using the real projected rate when available.
    # The declared weekly_rate_kg may exceed the actual deficit after safety
    # caps (min(500 kcal, 25% TDEE)), producing an ETA that the plan cannot
    # honour. Using the real rate gives the user a promise the plan can keep.
    estimated_weeks = wi.estimated_weeks
    estimated_date = wi.estimated_date
    if (
        projected is not None
        and wi.weight_to_lose_kg is not None
        and wi.weight_to_lose_kg > 0
    ):
        actual_rate = abs(projected)  # kg/week (positive)
        if actual_rate > 0:
            weeks = int(round(float(wi.weight_to_lose_kg) / actual_rate))
            estimated_weeks = weeks
            estimated_date = date.today() + timedelta(weeks=weeks)

    return WeightInsightsOut(
        bmi=wi.bmi,
        bmi_category=wi.bmi_category,
        bmi_label_es=wi.bmi_label_es,
        ideal_weight_min_kg=wi.ideal_weight_min_kg,
        ideal_weight_max_kg=wi.ideal_weight_max_kg,
        peterson_ideal_kg=wi.peterson_ideal_kg,
        devine_reference_kg=wi.devine_reference_kg,
        weight_to_lose_kg=wi.weight_to_lose_kg,
        weight_gap_direction=wi.weight_gap_direction,
        weekly_rate_kg=wi.weekly_rate_kg,
        weekly_rate_label=wi.weekly_rate_label,
        estimated_weeks=estimated_weeks,
        estimated_date=estimated_date,
        latam_context_note=wi.latam_context_note,
        projected_weekly_kg_actual=projected,
    )


def _to_resp(g: NutritionalGoals, wi: WeightInsights | None = None) -> GoalsResponse:
    kcal_target = (g.kcal_min + g.kcal_max) // 2
    return GoalsResponse(
        id=g.id,
        kcal_min=g.kcal_min,
        kcal_max=g.kcal_max,
        kcal_target=kcal_target,
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
        fiber_target_g=g.fiber_target_g,
        sodium_target_mg=g.sodium_target_mg,
        weight_insights=_weight_insights_out(wi, kcal_target=kcal_target, tdee=g.tdee),
    )


@router.get("/me/targets", response_model=GoalsResponse)
async def get_targets(current_user: CurrentUserDep, session: SessionDep) -> GoalsResponse:
    goals_uc = GetCurrentGoals(goals_repo=SqlNutritionalGoalsRepository(session))
    wi_uc = GetWeightInsights(profile_reader=SqlProfileReader(session))
    goals, wi = await _gather_goals_and_insights(
        goals_uc=goals_uc,
        wi_uc=wi_uc,
        user_id=current_user,
    )
    return _to_resp(goals, wi)


async def _gather_goals_and_insights(
    *, goals_uc: GetCurrentGoals, wi_uc: GetWeightInsights, user_id: object
) -> tuple[NutritionalGoals, WeightInsights | None]:
    """Run both use cases. Weight insights failure is non-fatal."""
    import asyncio

    goals_task = asyncio.create_task(goals_uc(user_id=user_id))
    wi_task = asyncio.create_task(wi_uc(user_id=user_id))
    try:
        goals = await goals_task
    except Exception:  # noqa: BLE001 — OK1: cancel orphaned wi_task then re-raise; goals error must propagate
        wi_task.cancel()
        raise
    try:
        wi = await wi_task
    except Exception:  # noqa: BLE001 — OK4: weight insights best-effort; goals response must not break for missing biometrics
        _log.warning("weight_insights_failed", user_id=str(user_id))
        wi = None
    return goals, wi


@router.get("/me/targets/history", response_model=list[GoalsResponse])
async def get_targets_history(
    current_user: CurrentUserDep,
    session: SessionDep,
    http_response: Response,
    limit: int = Query(default=20, ge=1, le=100, description="Max items to return"),
    cursor: datetime | None = Query(
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


@router.get("/me/weight-progress", response_model=WeightProgressResponse | None)
async def get_weight_progress(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> WeightProgressResponse | None:
    uc = GetWeightProgress(
        profile_reader=SqlProfileReader(session),
        tracking_reader=SqlTrackingReader(session),
    )
    wp = await uc(user_id=current_user)
    if wp is None:
        return None
    return WeightProgressResponse(
        slope_kg_per_week=float(wp.slope_kg_per_week) if wp.slope_kg_per_week is not None else None,
        trend_label=wp.trend_label,
        weight_points=wp.weight_points,
        days_tracked_last_14=wp.days_tracked_last_14,
        projected_goal_date=wp.projected_goal_date,
        vs_plan=wp.vs_plan,
    )
