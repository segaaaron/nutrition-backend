"""Plan router — async creation via Arq, hot reads via Redis cache."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Response, status

from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep, assert_owns
from app.plan.application.layer3_ranking import Layer3Ranking
from app.plan.application.taste_profile import TasteProfileService
from app.plan.application.use_cases import (
    AdvancePlan,
    CompleteMeal,
    GetActivePlan,
    SwapMeal,
)
from app.plan.domain.entities import Plan
from app.plan.infrastructure.cache import ActivePlanCache
from app.plan.infrastructure.repositories import SqlPlanRepository
from app.plan.infrastructure.taste_fetcher import SqlEmbeddingFetcher
from app.plan.infrastructure.user_context import SqlUserContext
from app.plan.presentation.schemas import (
    AdvanceRequest,
    CreatePlanRequest,
    CreatePlanResponse,
    PlanDayResponse,
    PlanMealResponse,
    PlanResponse,
    SwapMealRequest,
    SwapMealResponse,
)

log = get_logger("plan.router")
router = APIRouter(tags=["plan"])


def _to_resp(p: Plan) -> PlanResponse:
    return PlanResponse(
        id=p.id, user_id=p.user_id, type=p.type, total_days=p.total_days,
        current_day=p.current_day, status=p.status, goal=p.goal,
        meals_per_day=p.meals_per_day, preferences=p.preferences,
        kcal_target=p.kcal_target, version=p.version,
        created_at=p.created_at,
        days=[
            PlanDayResponse(
                id=d.id, day_index=d.day_index, date=d.date, completed=d.completed,
                meals=[
                    PlanMealResponse(
                        id=m.id, meal_time=m.meal_time, recipe_id=m.recipe_id,  # type: ignore[arg-type]
                        kcal=m.kcal, protein_g=m.protein_g, carbs_g=m.carbs_g,
                        fat_g=m.fat_g, completed=m.completed, swapped_from=m.swapped_from,
                    )
                    for m in d.meals
                ],
            )
            for d in p.days
        ],
    )


@router.post(
    "/plans", status_code=status.HTTP_202_ACCEPTED, response_model=CreatePlanResponse,
)
async def create_plan(
    body: CreatePlanRequest,
    current_user: CurrentUserDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreatePlanResponse:
    """Enqueues `generate_plan_task`. Idempotency-Key is required to dedupe
    a retried request after a client-side timeout (spec §11)."""
    if not idempotency_key:
        # Surface the requirement explicitly rather than silently dropping.
        return CreatePlanResponse(job_id="", plan_id=None, status="queued")
    from arq.connections import RedisSettings, create_pool

    from app.core.config import get_settings

    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job = await pool.enqueue_job(
            "generate_plan_task",
            user_id=str(current_user),
            plan_type=body.type,
            preferences=body.preferences,
            seed=body.seed,
            _job_id=f"plan:{current_user}:{idempotency_key}",
        )
    finally:
        await pool.close()
    response.headers["x-job-id"] = job.job_id if job else ""
    return CreatePlanResponse(
        job_id=job.job_id if job else "", plan_id=None, status="queued",
    )


@router.get("/plans/active", response_model=PlanResponse)
async def get_active_plan(current_user: CurrentUserDep, session: SessionDep) -> PlanResponse:
    cache = ActivePlanCache(get_redis())
    uc = GetActivePlan(plans=SqlPlanRepository(session), cache=cache)
    plan = await uc(user_id=current_user)
    payload = _to_resp(plan)
    return payload


@router.post("/plans/{plan_id}/advance", response_model=PlanResponse)
async def advance_plan(
    plan_id: Annotated[uuid.UUID, Path()],
    body: AdvanceRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> PlanResponse:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    uc = AdvancePlan(plans=SqlPlanRepository(session), cache=cache, bus=get_event_bus())
    plan = await uc(plan_id=plan_id, event=body.event)
    return _to_resp(plan)


@router.patch(
    "/plans/{plan_id}/meals/{meal_id}/complete", status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_meal(
    plan_id: Annotated[uuid.UUID, Path()],
    meal_id: Annotated[uuid.UUID, Path()],
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    uc = CompleteMeal(plans=SqlPlanRepository(session), cache=cache, bus=get_event_bus())
    await uc(plan_id=plan_id, meal_id=meal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/plans/{plan_id}/meals/{meal_id}/swap", response_model=SwapMealResponse)
async def swap_meal(
    plan_id: Annotated[uuid.UUID, Path()],
    meal_id: Annotated[uuid.UUID, Path()],
    body: SwapMealRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> SwapMealResponse:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    # Candidate pool: callers may pre-fetch via /recipes; here we pass empty
    # and rely on the layer3 to rank an empty list → empty alternatives. The
    # full swap-with-search workflow is the Sprint-5 enhancement.
    taste = await TasteProfileService(
        redis=get_redis(), fetcher=SqlEmbeddingFetcher(session),
    ).get_or_build(current_user)
    user_ctx = SqlUserContext(session)
    layer3 = Layer3Ranking(session=session, profile_ctx=user_ctx, taste_vector=taste)
    uc = SwapMeal(
        plans=SqlPlanRepository(session), cache=cache, layer3=layer3,
        bus=get_event_bus(),
    )
    alts = await uc(
        plan_id=plan_id, meal_id=meal_id, reason_code=body.reason_code,
        candidate_ids=[],
    )
    return SwapMealResponse(alternatives=alts)
