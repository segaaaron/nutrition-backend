"""Plan router — async creation via Arq, hot reads via Redis cache."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, Path, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.event_bus import get_event_bus
from app.core.idempotency import (
    IdempotencyConflict,
    cached_to_response,
    lookup_redis,
    remember_redis,
    require_idempotency_key,
)
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep, assert_owns
from app.nutrition.infrastructure.compute_goals_adapter import InlineComputeGoals
from app.plan.application.layer3_ranking import Layer3Ranking
from app.plan.application.taste_profile import TasteProfileService
from app.plan.application.use_cases import (
    AdvancePlan,
    CompleteMeal,
    GetActivePlan,
    SwapMeal,
)
from app.plan.domain.entities import Plan
from app.plan.domain.water_view import build_water_view
from app.plan.infrastructure.cache import ActivePlanCache
from app.plan.infrastructure.plan_enqueuer import enqueue_generate_plan
from app.plan.infrastructure.repositories import SqlPlanRepository
from app.plan.infrastructure.taste_fetcher import SqlEmbeddingFetcher
from app.plan.infrastructure.user_context import SqlUserContext
from app.plan.presentation.schemas import (
    AdvanceRequest,
    CreatePlanRequest,
    CreatePlanResponse,
    PlanDayResponse,
    PlanJobRef,
    PlanMealIngredient,
    PlanMealResponse,
    PlanResponse,
    SwapMealRequest,
    SwapMealResponse,
    WaterSlotResponse,
    WaterTargetResponse,
)
from app.profile.application.use_cases import CompleteOnboarding
from app.profile.domain.entities import UserProfile
from app.profile.infrastructure.repositories import SqlProfileRepository
from app.profile.presentation.schemas import ProfileResponse
from app.recipes.infrastructure.models import RecipeComponentModel, RecipeModel
from app.shared.i18n import Locale, LocaleDep

log = get_logger("plan.router")
router = APIRouter(tags=["plan"])


async def _hydrate_water_view(plan: Plan, session: AsyncSession, locale: Locale) -> None:
    """Attach `water_view` to a Plan read from storage.

    The plan persistence layer does not store the hydration schedule
    (storage truth lives in `nutritional_goals.water_ml`). At read time
    we fetch the current target and build the view on the fly using the
    *request-time* locale (Phase 2 wiring — see plan T2.1 / D1 priority).
    No-op if the view is already populated (e.g. fresh `CreatePlan` output).
    """
    if plan.water_view is not None:
        return
    user_ctx = SqlUserContext(session)
    targets = await user_ctx.get_user_targets(plan.user_id)
    water_ml = targets.get("water_ml")
    if water_ml is None or int(water_ml) <= 0:
        return
    plan.water_view = build_water_view(
        total_ml=int(water_ml),
        locale=locale,
    )


@dataclass(frozen=True)
class _RecipeData:
    """Display + full detail for one recipe, embedded into plan meals."""

    name_en: str
    name_translations: dict[str, str]
    description_en: str | None
    description_translations: dict[str, str]
    image_url: str | None
    prep_min: int | None
    instructions_en: list[str]
    instructions_translations: dict[str, list[str]]
    fiber_g: int | None
    sugar_g: int | None
    sodium_mg: int | None
    sat_fat_g: int | None
    tags: list[str]
    allergens: list[str]
    # (free_text_name, amount_g, position) ordered by position — native amounts.
    components: list[tuple[str | None, Decimal | None, int]] = field(default_factory=list)


async def _load_recipe_translations(
    plan: Plan,
    session: AsyncSession,
) -> dict[uuid.UUID, _RecipeData]:
    """Batched fetch of display + full detail for every recipe_id in plan.

    Embeds micros, tags, allergens and ingredients so iOS renders a meal
    without a follow-up ``GET /recipes/{id}``.
    """
    recipe_ids: set[uuid.UUID] = {
        m.recipe_id
        for d in plan.days
        for m in d.meals
        if m.recipe_id is not None
    }
    if not recipe_ids:
        return {}
    stmt = select(
        RecipeModel.id,
        RecipeModel.name_en,
        RecipeModel.name_translations,
        RecipeModel.description_en,
        RecipeModel.description_translations,
        RecipeModel.image_url,
        RecipeModel.prep_min,
        RecipeModel.instructions_en,
        RecipeModel.instructions_translations,
        RecipeModel.fiber_g,
        RecipeModel.sugar_g,
        RecipeModel.sodium_mg,
        RecipeModel.sat_fat_g,
        RecipeModel.tags,
        RecipeModel.allergens,
    ).where(RecipeModel.id.in_(recipe_ids))
    rows = (await session.execute(stmt)).all()

    comp_stmt = (
        select(
            RecipeComponentModel.recipe_id,
            RecipeComponentModel.free_text_name,
            RecipeComponentModel.amount_g,
            RecipeComponentModel.position,
        )
        .where(RecipeComponentModel.recipe_id.in_(recipe_ids))
        .order_by(RecipeComponentModel.recipe_id, RecipeComponentModel.position)
    )
    comps: dict[uuid.UUID, list[tuple[str | None, Decimal | None, int]]] = defaultdict(list)
    for cr in (await session.execute(comp_stmt)).all():
        comps[cr[0]].append((cr[1], cr[2], cr[3]))

    return {
        row[0]: _RecipeData(
            name_en=row[1],
            name_translations=dict(row[2] or {}),
            description_en=row[3],
            description_translations=dict(row[4] or {}),
            image_url=row[5],
            prep_min=row[6],
            instructions_en=list(row[7] or []),
            instructions_translations=dict(row[8] or {}),
            fiber_g=row[9],
            sugar_g=row[10],
            sodium_mg=row[11],
            sat_fat_g=row[12],
            tags=list(row[13] or []),
            allergens=[str(a) for a in (row[14] or [])],
            components=comps.get(row[0], []),
        )
        for row in rows
    }


def _localize_name(
    rid: uuid.UUID | None,
    translations: Mapping[uuid.UUID, _RecipeData],
    locale: Locale,
) -> str | None:
    if rid is None:
        return None
    entry = translations.get(rid)
    if entry is None:
        return None
    return entry.name_translations.get(locale) or entry.name_en


def _localize_description(
    rid: uuid.UUID | None,
    translations: Mapping[uuid.UUID, _RecipeData],
    locale: Locale,
) -> str | None:
    if rid is None:
        return None
    entry = translations.get(rid)
    if entry is None:
        return None
    return entry.description_translations.get(locale) or entry.description_en


def _build_meal_resp(
    m: object,
    tr: Mapping[uuid.UUID, _RecipeData],
    locale: Locale,
) -> PlanMealResponse:
    from app.plan.domain.entities import PlanMeal as _PlanMeal  # local to avoid cycle
    assert isinstance(m, _PlanMeal)
    data = tr.get(m.recipe_id) if m.recipe_id is not None else None
    if data is not None:
        instructions = data.instructions_translations.get(locale) or data.instructions_en
        ingredients = [
            PlanMealIngredient(name=name, amount_g=amount, position=pos)
            for (name, amount, pos) in data.components
        ]
    else:
        instructions = []
        ingredients = []
    return PlanMealResponse(
        id=m.id,
        meal_time=m.meal_time,
        recipe_id=m.recipe_id,
        name_localized=_localize_name(m.recipe_id, tr, locale),
        description_localized=_localize_description(m.recipe_id, tr, locale),
        kcal=m.kcal,
        protein_g=m.protein_g,
        carbs_g=m.carbs_g,
        fat_g=m.fat_g,
        scaled_factor=m.scaled_factor,
        image_url=data.image_url if data is not None else None,
        prep_min=data.prep_min if data is not None else None,
        instructions_localized=instructions,
        fiber_g=data.fiber_g if data is not None else None,
        sugar_g=data.sugar_g if data is not None else None,
        sodium_mg=data.sodium_mg if data is not None else None,
        sat_fat_g=data.sat_fat_g if data is not None else None,
        tags=data.tags if data is not None else [],
        allergens=data.allergens if data is not None else [],
        ingredients=ingredients,
        completed=m.completed,
        swapped_from=m.swapped_from,
    )


def _slot(meals: list, slot: str, tr: Mapping[uuid.UUID, _RecipeData], locale: Locale) -> PlanMealResponse | None:
    for m in meals:
        if m.meal_time == slot:
            return _build_meal_resp(m, tr, locale)
    return None


def _to_resp(
    p: Plan,
    translations: Mapping[uuid.UUID, _RecipeData] | None = None,
    locale: Locale = "es",
) -> PlanResponse:
    tr = translations or {}
    water_target = (
        WaterTargetResponse(
            total_ml=p.water_view.total_ml,
            glass_ml=p.water_view.glass_ml,
            n_glasses=p.water_view.n_glasses,
            schedule=[
                WaterSlotResponse(time=s.time, ml=s.ml, label=s.label)
                for s in p.water_view.schedule
            ],
            message=p.water_view.message,
        )
        if p.water_view is not None
        else None
    )
    return PlanResponse(
        id=p.id,
        user_id=p.user_id,
        type=p.type,
        total_days=p.total_days,
        current_day=p.current_day,
        status=p.status,
        goal=p.goal,
        meals_per_day=p.meals_per_day,
        preferences=p.preferences,
        kcal_target=p.kcal_target,
        version=p.version,
        created_at=p.created_at,
        days=[
            PlanDayResponse(
                id=d.id,
                day_index=d.day_index,
                date=d.date,
                completed=d.completed,
                kcal_actual=d.kcal_actual,
                within_band=d.within_band,
                breakfast=_slot(d.meals, "breakfast", tr, locale),
                lunch=_slot(d.meals, "lunch", tr, locale),
                dinner=_slot(d.meals, "dinner", tr, locale),
                snack=_slot(d.meals, "snack", tr, locale),
            )
            for d in p.days
        ],
        water_target=water_target,
        slot_targets=p.slot_targets,
    )


def _profile_to_resp(p: UserProfile) -> ProfileResponse:
    """Project a domain ``UserProfile`` into the public response schema.

    Kept private to this router — the profile router has its own copy
    because the projection is trivial and importing across presentation
    layers would create a cycle.
    """
    return ProfileResponse(
        user_id=p.user_id,
        name=p.name,
        age=p.age,
        sex=p.sex,
        weight_kg=p.weight_kg,
        height_cm=p.height_cm,
        goal=p.goal,
        activity_level=p.activity_level,
        medical_conditions=p.medical_conditions,
        other_condition=p.other_condition,
        allergies=p.allergies,
        other_allergy=p.other_allergy,
        country=p.country,
        region=p.region,
        locale=p.locale,
        units=p.units,
        dietary_pattern=p.dietary_pattern,
        onboarding_completed=p.onboarding_completed,
        updated_at=p.updated_at,
        plan_job=None,
    )


@router.post(
    "/plans",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreatePlanResponse,
)
async def create_plan(
    body: CreatePlanRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    request: Request,
    response: Response,
    locale: LocaleDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    """Single endpoint for plan generation — serves BOTH iOS contexts:

    * **Onboarding final step.** Client posts ``{"profile": {...}}`` with the
      full :class:`OnboardingRequest` payload. The handler upserts the
      profile + computes nutritional goals atomically (same request tx via
      :class:`CompleteOnboarding`), then enqueues plan generation. If the
      profile save raises, the request tx rolls back AND no plan job is
      enqueued (the enqueue step runs only after profile commit succeeds).
    * **Regeneration from inside the app.** Client posts ``{}`` (body empty
      or just plan-shaping fields). The handler reads the existing profile;
      missing profile → 422 ``profile_not_found``.

    ``Idempotency-Key`` (UUIDv4) is REQUIRED. Replay within 24 h returns
    the cached 202 body verbatim; same key with a different body
    fingerprint → 409.
    """
    key = require_idempotency_key(idempotency_key)

    raw_body = await request.body()
    redis = get_redis()
    try:
        skey, cached = await lookup_redis(
            redis=redis,
            user_id=str(current_user),
            path=request.url.path,
            raw_key=key,
            body=raw_body,
        )
    except IdempotencyConflict as exc:
        raise ConflictError(
            "idempotency_body_mismatch",
            field="Idempotency-Key",
            key=key,
            reason="Same Idempotency-Key was used with a different request body",
        ) from exc
    if cached is not None:
        return cached_to_response(cached)

    # Branch A — body includes a full OnboardingRequest: persist profile +
    # goals INLINE, in the same request tx, before enqueueing.
    profile_resp: ProfileResponse | None = None
    if body.profile is not None:
        bus = get_event_bus()
        complete_onboarding = CompleteOnboarding(
            profiles=SqlProfileRepository(session),
            bus=bus,
            compute_goals=InlineComputeGoals(session=session, bus=bus),
        )
        payload = body.profile.model_dump(exclude_none=False)
        payload["height_cm"] = body.profile.resolved_height_cm
        payload.pop("height_m", None)
        # On any failure (validation, MVP gate, goals compute) the
        # exception propagates → SessionDep rolls back → no plan job
        # enqueued. This is the "atomic profile save or no plan"
        # invariant.
        saved_profile = await complete_onboarding(
            user_id=current_user, payload=payload
        )
        profile_resp = _profile_to_resp(saved_profile)
    else:
        # Branch B — regeneration. Profile must already exist.
        repo = SqlProfileRepository(session)
        existing = await repo.get(current_user)
        if existing is None:
            # 422 (not 404) per the iOS contract — UI shows the
            # onboarding-required message and routes the user back
            # rather than a generic "not found" screen.
            raise BusinessRuleViolation("profile_not_found")

    job_id = await enqueue_generate_plan(
        user_id=current_user,
        plan_type=body.type,
        preferences=body.preferences,
        seed=body.seed,
        locale=locale,
        job_id=f"plan:{current_user}:{key}",
    )
    resolved_job_id = job_id or ""
    response.headers["x-job-id"] = resolved_job_id

    payload_out = CreatePlanResponse(
        job_id=resolved_job_id,
        plan_id=None,
        status="queued",
        profile=profile_resp,
        plan_job=PlanJobRef(job_id=resolved_job_id, status="queued")
        if resolved_job_id
        else None,
    )
    await remember_redis(
        redis=redis,
        storage_key=skey,
        body=raw_body,
        response_body=payload_out.model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED,
    )
    return Response(
        content=payload_out.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_202_ACCEPTED,
        headers={"x-job-id": resolved_job_id},
    )


@router.get("/plans/active", response_model=PlanResponse)
async def get_active_plan(
    current_user: CurrentUserDep,
    session: SessionDep,
    locale: LocaleDep,
) -> PlanResponse:
    cache = ActivePlanCache(get_redis())
    uc = GetActivePlan(plans=SqlPlanRepository(session), cache=cache)
    plan = await uc(user_id=current_user)
    await _hydrate_water_view(plan, session, locale)
    translations = await _load_recipe_translations(plan, session)
    return _to_resp(plan, translations=translations, locale=locale)


@router.post("/plans/{plan_id}/advance", response_model=PlanResponse)
async def advance_plan(
    plan_id: Annotated[uuid.UUID, Path()],
    body: AdvanceRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    locale: LocaleDep,
) -> PlanResponse:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    uc = AdvancePlan(plans=SqlPlanRepository(session), cache=cache, bus=get_event_bus())
    plan = await uc(plan_id=plan_id, event=body.event)
    await _hydrate_water_view(plan, session, locale)
    translations = await _load_recipe_translations(plan, session)
    return _to_resp(plan, translations=translations, locale=locale)


@router.patch(
    "/plans/{plan_id}/meals/{meal_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
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
    locale: LocaleDep,  # noqa: ARG001 — reserved for future localized swap reasons (Phase 4 errors)
) -> SwapMealResponse:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    # Candidate pool: callers may pre-fetch via /recipes; here we pass empty
    # and rely on the layer3 to rank an empty list → empty alternatives. The
    # full swap-with-search workflow is the Sprint-5 enhancement.
    taste = await TasteProfileService(
        redis=get_redis(),
        fetcher=SqlEmbeddingFetcher(session),
    ).get_or_build(current_user)
    user_ctx = SqlUserContext(session)
    layer3 = Layer3Ranking(session=session, profile_ctx=user_ctx, taste_vector=taste)
    uc = SwapMeal(
        plans=SqlPlanRepository(session),
        cache=cache,
        layer3=layer3,
        bus=get_event_bus(),
    )
    alts = await uc(
        plan_id=plan_id,
        meal_id=meal_id,
        reason_code=body.reason_code,
        candidate_ids=[],
    )
    return SwapMealResponse(alternatives=alts)
