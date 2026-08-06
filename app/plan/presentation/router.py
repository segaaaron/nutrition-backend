"""Plan router — async creation via Arq, hot reads via Redis cache."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Path, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache_keys import CacheKeys
from app.core.metrics import (
    MEAL_SWAPPED_TOTAL,
    PLAN_CREATED_TOTAL,
    RETENTION_NUDGE_SHOWN_TOTAL,
    WEEK_RECAP_SHOWN_TOTAL,
)
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
from app.nutrition.domain.weight_projection import expected_weekly_change
from app.nutrition.infrastructure.compute_goals_adapter import InlineComputeGoals
from app.plan.application.layer1_eligibility import Layer1Eligibility
from app.plan.application.layer3_ranking import Layer3Ranking
from app.plan.application.taste_profile import TasteProfileService
from app.plan.application.use_cases import (
    AdvancePlan,
    CompleteMeal,
    GetActivePlan,
    SwapMeal,
)
from app.plan.domain.entities import Plan
from app.plan.domain.meal_rationale import build_meal_rationale
from app.plan.domain.water_view import build_water_view
from app.plan.infrastructure.cache import ActivePlanCache
from app.plan.infrastructure.plan_enqueuer import enqueue_and_wait_plan
from app.plan.infrastructure.profile_reader import SqlEligibilityProfileReader
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
    RetentionNudge,
    SwapMealRequest,
    SwapMealResponse,
    TodaySummary,
    WaterSlotResponse,
    WaterTargetResponse,
    WeekRecap,
    WeightProjectionResponse,
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
    # (free_text_name, name_en, amount_g, position, modifier) ordered by position.
    components: list[tuple[str | None, str | None, Decimal | None, int, str | None]] = field(
        default_factory=list
    )


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
            RecipeComponentModel.name_en,
            RecipeComponentModel.amount_g,
            RecipeComponentModel.position,
            RecipeComponentModel.modifier,
        )
        .where(RecipeComponentModel.recipe_id.in_(recipe_ids))
        .order_by(RecipeComponentModel.recipe_id, RecipeComponentModel.position)
    )
    comps: dict[uuid.UUID, list[tuple[str | None, str | None, Decimal | None, int, str | None]]] = defaultdict(
        list
    )
    for cr in (await session.execute(comp_stmt)).all():
        comps[cr[0]].append((cr[1], cr[2], cr[3], cr[4], cr[5]))

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
    # BE-6 (2026-07-11): fall back to the Spanish translation (the catalog's
    # authoritative language) BEFORE the raw name_en. name_en is clean English
    # but description_en is Spanish for many rows, so falling to the *_en fields
    # produced a mixed English-name / Spanish-description card. Falling both to
    # the 'es' translation keeps name and description in the SAME language.
    return (
        entry.name_translations.get(locale)
        or entry.name_translations.get("es")
        or entry.name_en
    )


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
    return (
        entry.description_translations.get(locale)
        or entry.description_translations.get("es")
        or entry.description_en
    )


def _build_meal_resp(
    m: object,
    tr: Mapping[uuid.UUID, _RecipeData],
    locale: Locale,
    goal: str | None = None,
) -> PlanMealResponse:
    from app.plan.domain.entities import PlanMeal as _PlanMeal  # local to avoid cycle
    assert isinstance(m, _PlanMeal)
    data = tr.get(m.recipe_id) if m.recipe_id is not None else None
    if data is not None:
        instructions = data.instructions_translations.get(locale) or data.instructions_en
        want_en = locale == "en"
        ingredients = [
            PlanMealIngredient(
                name=name,
                # BE-9: EN name when the request is English and a translation
                # exists; otherwise the raw free_text_name (mostly ES).
                name_localized=(name_en if (want_en and name_en) else name),
                amount_g=amount,
                position=pos,
                modifier=modifier,
            )
            for (name, name_en, amount, pos, modifier) in data.components
        ]
    else:
        instructions = []
        ingredients = []
    # Sprint A1 — fact-based rationale from the meal's real macros + user goal.
    _rat = build_meal_rationale(
        protein_g=m.protein_g,
        fiber_g=data.fiber_g if data is not None else None,
        meal_time=m.meal_time,
        goal=goal,
    )
    rationale = _rat.get(locale) or _rat["es"]
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
        rationale_localized=rationale,
    )


def _slot(
    meals: list[Any],
    slot: str,
    tr: Mapping[uuid.UUID, _RecipeData],
    locale: Locale,
    goal: str | None = None,
) -> PlanMealResponse | None:
    for m in meals:
        if m.meal_time == slot:
            return _build_meal_resp(m, tr, locale, goal=goal)
    return None


async def _fetch_latest_tdee(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    """Latest TDEE from nutritional_goals for the A2 weight-change projection."""
    from sqlalchemy import text as _text

    row = (
        await session.execute(
            _text(
                "SELECT tdee FROM nutritional_goals WHERE user_id = :uid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"uid": str(user_id)},
        )
    ).scalar()
    return int(row) if row is not None else None


async def _compute_retention_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    _today: "date | None" = None,
) -> dict:
    """E4 — lazy retention fields for GET /plans/active. Zero crons; computed on request.

    _today is injectable for unit tests; defaults to date.today().
    """
    from datetime import date as _date

    from sqlalchemy import text as _text

    today = _today if _today is not None else _date.today()

    # Last food log date and current daily streak.
    last_log_scalar = (
        await session.execute(
            _text("SELECT MAX(date) FROM food_logs WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    ).scalar()
    days_since: int | None = (today - last_log_scalar).days if last_log_scalar else None

    streak_scalar = (
        await session.execute(
            _text("SELECT value FROM streaks WHERE user_id = :uid AND type = 'daily'"),
            {"uid": str(user_id)},
        )
    ).scalar()
    current_streak = int(streak_scalar or 0)

    # Days since account creation (users.created_at).
    created_scalar = (
        await session.execute(
            _text("SELECT created_at::date FROM users WHERE id = :uid"),
            {"uid": str(user_id)},
        )
    ).scalar()
    days_active = (today - created_scalar).days if created_scalar else 0

    result: dict = {}

    # H3 — retention_nudge
    nudge_type: str | None = None
    if days_since in (1, 2):
        nudge_type = "streak_at_risk"
    elif days_since is not None and days_since >= 3:
        nudge_type = "comeback"
    elif 7 <= days_active <= 9 and current_streak >= 5:
        nudge_type = "week1_strong"
    elif 13 <= days_active <= 16 and days_since == 0:
        nudge_type = "two_weeks_milestone"

    if nudge_type:
        if nudge_type == "streak_at_risk":
            msg_es = f"Tu racha de {current_streak} días está en riesgo. Registra algo hoy."
            msg_en = f"Your {current_streak}-day streak is at risk. Log something today."
        elif nudge_type == "comeback":
            msg_es = f"Llevas {days_since} días sin registrar. Hoy es un buen día para volver."
            msg_en = f"You've been away {days_since} days. Today's a good day to return."
        elif nudge_type == "week1_strong":
            msg_es = "Primera semana fuerte. Sigue así."
            msg_en = "Strong first week. Keep going."
        else:
            msg_es = "Dos semanas cumplidas. Estás formando un hábito."
            msg_en = "Two weeks done. You're building a habit."
        result["retention_nudge"] = RetentionNudge(
            type=nudge_type,  # type: ignore[arg-type]
            streak_days=current_streak if nudge_type == "streak_at_risk" else None,
            days_away=days_since if nudge_type == "comeback" else None,
            message_es=msg_es,
            message_en=msg_en,
        )
        RETENTION_NUDGE_SHOWN_TOTAL.labels(nudge_type=nudge_type).inc()

    # H4 — week_recap (Sundays or every 7th day_active)
    dow = today.isoweekday()  # 7 = Sunday
    if dow == 7 or (days_active > 0 and days_active % 7 == 0):
        days_logged_scalar = (
            await session.execute(
                _text(
                    "SELECT COUNT(DISTINCT date) FROM food_logs"
                    " WHERE user_id = :uid AND date >= CURRENT_DATE - 6"
                ),
                {"uid": str(user_id)},
            )
        ).scalar()
        days_logged = int(days_logged_scalar or 0)
        if days_logged == 7:
            msg_es, msg_en = "¡Semana perfecta! 7 de 7 días registrados.", "Perfect week! 7 of 7 days logged."
        elif days_logged >= 5:
            msg_es = f"Esta semana registraste {days_logged} de 7 días. ¡Casi perfecto!"
            msg_en = f"You logged {days_logged} of 7 days this week. Almost perfect!"
        elif days_logged >= 3:
            msg_es = f"Registraste {days_logged} de 7 días. Puedes más la próxima semana."
            msg_en = f"You logged {days_logged} of 7 days. You can do more next week."
        else:
            msg_es = f"Solo {days_logged} de 7 días registrados. Esta semana lo mejoramos."
            msg_en = f"Only {days_logged} of 7 days logged. We improve that this week."
        result["week_recap"] = WeekRecap(
            days_logged=days_logged,
            days_total=7,
            message_es=msg_es,
            message_en=msg_en,
        )
        WEEK_RECAP_SHOWN_TOTAL.inc()

    # H5 — today_summary (kcal progress)
    kcal_row = (
        await session.execute(
            _text(
                """
                SELECT (g.kcal_min + g.kcal_max) / 2 AS target,
                       COALESCE(SUM(fl.kcal), 0)::int AS logged
                  FROM nutritional_goals g
                  LEFT JOIN food_logs fl
                    ON fl.user_id = g.user_id AND fl.date = CURRENT_DATE
                 WHERE g.user_id = :uid
                 GROUP BY g.kcal_min, g.kcal_max, g.valid_from
                 ORDER BY g.valid_from DESC
                 LIMIT 1
                """
            ),
            {"uid": str(user_id)},
        )
    ).mappings().first()
    if kcal_row and kcal_row["target"]:
        target = int(kcal_row["target"])
        logged = int(kcal_row["logged"] or 0)
        remaining = max(target - logged, 0)
        pct = min(int(logged * 100 / target), 100) if target > 0 else 0
        result["today_summary"] = TodaySummary(
            kcal_logged=logged,
            kcal_target=target,
            kcal_remaining=remaining,
            pct_complete=pct,
        )

    return result


def _to_resp(
    p: Plan,
    translations: Mapping[uuid.UUID, _RecipeData] | None = None,
    locale: Locale = "es",
    tdee: int | None = None,
) -> PlanResponse:
    tr = translations or {}
    # Sprint A2 — expected weekly weight change when we know the TDEE the plan
    # was built against. Pure display; never gates or alters the plan.
    projection: WeightProjectionResponse | None = None
    if tdee is not None and p.kcal_target is not None:
        wp = expected_weekly_change(kcal_target=p.kcal_target, tdee=tdee)
        projection = WeightProjectionResponse(
            weekly_kg=float(wp.weekly_kg),
            ci_low_kg=float(wp.ci_low_kg),
            ci_high_kg=float(wp.ci_high_kg),
        )
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
                breakfast=_slot(d.meals, "breakfast", tr, locale, goal=p.goal),
                morning_snack=_slot(d.meals, "morning_snack", tr, locale, goal=p.goal),
                lunch=_slot(d.meals, "lunch", tr, locale, goal=p.goal),
                afternoon_snack=_slot(d.meals, "afternoon_snack", tr, locale, goal=p.goal),
                dinner=_slot(d.meals, "dinner", tr, locale, goal=p.goal),
                snack=_slot(d.meals, "snack", tr, locale, goal=p.goal),
                protein_actual=sum(m.protein_g or 0 for m in d.meals),
                fiber_daily=sum(
                    int(round((tr[m.recipe_id].fiber_g or 0) * (m.scaled_factor or 1.0)))
                    for m in d.meals
                    if m.recipe_id is not None and m.recipe_id in tr
                ),
            )
            for d in p.days
        ],
        water_target=water_target,
        slot_targets=p.slot_targets,
        expected_weekly_change=projection,
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

    # Per-user plan-generation rate limit: max 10 new plans per hour.
    # Idempotency replays (same key, same body) bypass this gate via the
    # cache check below — only genuinely new requests count toward the cap.
    _plan_rl_key = CacheKeys.PLAN_GEN_RL.format(user_id=current_user)
    try:
        _plan_rl_count = await redis.incr(_plan_rl_key)
        if _plan_rl_count == 1:
            await redis.expire(_plan_rl_key, 3600)
        if _plan_rl_count > 10:
            raise BusinessRuleViolation("plan_generation_rate_exceeded")
    except BusinessRuleViolation:
        raise
    except Exception:  # noqa: BLE001 — Redis down → fail-open, allow the request
        pass
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

    # BE-4a/BE-6: plan content language = the user's app language, NEVER the
    # device Accept-Language header (a Spanish user on an English phone must
    # still get a Spanish plan). Precedence: explicit body locale > stored
    # profile.locale (resolved in CreatePlan) > "es". The header (`locale`) is
    # deliberately dropped here — passing None lets CreatePlan fall to the
    # stored profile.locale.
    effective_locale = (
        body.profile.locale if body.profile and body.profile.locale else None
    )
    # BE-7 (2026-07-11): block the request until the worker finishes and return
    # status="ready" + plan_id, so iOS ties `loading` to the real completion
    # (`loading → await → loaded`) with ZERO client-side polling. On timeout we
    # degrade to the async 202 + queued so a slow generation still succeeds via
    # the client's fallback path.
    job_id, ready_plan_id = await enqueue_and_wait_plan(
        user_id=current_user,
        plan_type=body.type,
        preferences=body.preferences,
        seed=body.seed,
        locale=effective_locale,
        job_id=f"plan:{current_user}:{key}",
    )
    resolved_job_id = job_id or ""
    response.headers["x-job-id"] = resolved_job_id
    # The worker returns plan_id as a str; CreatePlanResponse.plan_id is a
    # strict UUID. Coerce here (malformed/None → treat as not-ready 202).
    ready_plan_uuid: uuid.UUID | None = None
    if ready_plan_id:
        try:
            ready_plan_uuid = uuid.UUID(ready_plan_id)
        except ValueError:
            ready_plan_uuid = None
    is_ready = ready_plan_uuid is not None
    if is_ready:
        _goal = str(body.profile.goal) if body.profile and body.profile.goal else "regen"
        _has_cond = "yes" if body.profile and body.profile.medical_conditions else "no"
        PLAN_CREATED_TOTAL.labels(goal=_goal, has_condition=_has_cond).inc()
    out_status: Literal["queued", "generating", "ready"] = (
        "ready" if is_ready else "queued"
    )
    http_status = status.HTTP_200_OK if is_ready else status.HTTP_202_ACCEPTED

    payload_out = CreatePlanResponse(
        job_id=resolved_job_id,
        plan_id=ready_plan_uuid,
        status=out_status,
        profile=profile_resp,
        plan_job=PlanJobRef(job_id=resolved_job_id, status=out_status)
        if resolved_job_id
        else None,
    )
    await remember_redis(
        redis=redis,
        storage_key=skey,
        body=raw_body,
        response_body=payload_out.model_dump(mode="json"),
        status_code=http_status,
    )
    return Response(
        content=payload_out.model_dump_json(),
        media_type="application/json",
        status_code=http_status,
        headers={"x-job-id": resolved_job_id},
    )


@router.get("/plans/active", response_model=PlanResponse)
async def get_active_plan(
    current_user: CurrentUserDep,
    session: SessionDep,
    locale: LocaleDep,
) -> PlanResponse:
    from sqlalchemy import text as _text

    cache = ActivePlanCache(get_redis())
    uc = GetActivePlan(plans=SqlPlanRepository(session), cache=cache)
    plan = await uc(user_id=current_user)
    await _hydrate_water_view(plan, session, locale)
    translations = await _load_recipe_translations(plan, session)

    # Paywall signal: True only on first ever completed plan for free-tier users.
    paywall_signal = False
    plan_count_row = (
        await session.execute(
            _text("SELECT COUNT(*) FROM plans WHERE user_id = :uid"),
            {"uid": str(current_user)},
        )
    ).scalar()
    if int(plan_count_row or 0) == 1:
        sub_row = (
            await session.execute(
                _text(
                    """
                    SELECT plan FROM subscriptions
                     WHERE user_id = :uid
                       AND status NOT IN ('cancelled','incomplete')
                     ORDER BY created_at DESC LIMIT 1
                """
                ),
                {"uid": str(current_user)},
            )
        ).mappings().first()
        if sub_row is None or sub_row["plan"] == "free":
            paywall_signal = True

    # Sprint A2 — expected-weight-change projection (display).
    tdee = await _fetch_latest_tdee(session, current_user)
    resp = _to_resp(plan, translations=translations, locale=locale, tdee=tdee)

    # E4 — retention hooks H3/H4/H5 (lazy eval, no cron).
    retention = await _compute_retention_context(session, current_user)
    resp = resp.model_copy(
        update={
            "paywall_signal": paywall_signal,
            **retention,
        }
    )

    # G — weekly review: lazy eval on Sunday, idempotent via Redis.
    # Replaces the old cron (CRON_JOBS=[]) with zero infrastructure: the
    # first GET /plans/active on any Sunday triggers the review; subsequent
    # calls that day are skipped via the Redis NX lock (TTL 8d covers the
    # full week with a 1-day margin so it never fires twice in one week).
    await _maybe_send_weekly_review(session, current_user)

    return resp


async def _maybe_send_weekly_review(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    """Fire weekly_review at most once per calendar week, on Sunday, lazy."""
    from datetime import date as _date

    from app.coach.application.features import weekly_review

    today = _date.today()
    # isoweekday(): Monday=1 … Sunday=7
    if today.isoweekday() != 7:
        return
    iso_week = today.isocalendar()[1]
    iso_year = today.isocalendar()[0]
    redis = get_redis()
    lock_key = f"wkly_rv:{user_id}:{iso_year}w{iso_week}"
    # SET NX: only the first caller this week acquires the lock.
    acquired = await redis.set(lock_key, "1", nx=True, ex=8 * 86400)
    if not acquired:
        return
    try:
        await weekly_review(session, user_id=user_id)
    except Exception:  # noqa: BLE001
        # Release lock so next call can retry; don't let a coach failure
        # surface as a plan-fetch error.
        await redis.delete(lock_key)
        raise


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
    tdee = await _fetch_latest_tdee(session, current_user)
    return _to_resp(plan, translations=translations, locale=locale, tdee=tdee)


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

    # Load the meal to know its slot so Layer1 can filter the right candidates.
    plan_repo = SqlPlanRepository(session)
    plan = await plan_repo.get(plan_id)
    meal = plan.find_meal(meal_id) if plan else None
    meal_time = meal.meal_time if meal else "lunch"

    # Layer1 — eligibility filter yields the full valid candidate pool for this slot.
    layer1 = Layer1Eligibility(
        session=session,
        profile_reader=SqlEligibilityProfileReader(session),
    )
    candidate_ids = await layer1(user_id=current_user, meal_time=meal_time)

    # Exclude the current recipe so the swap always picks something different.
    if meal and meal.recipe_id and meal.recipe_id in candidate_ids:
        candidate_ids.remove(meal.recipe_id)

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
        candidate_ids=candidate_ids,
    )
    MEAL_SWAPPED_TOTAL.labels(reason=body.reason_code or "none").inc()
    return SwapMealResponse(alternatives=alts)
