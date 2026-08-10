"""Profile FastAPI router (/me, /me/onboarding, /me/locale).

Note (2026-06-09): ``POST /me/onboarding`` no longer auto-enqueues a plan
generation job. The single source of truth for plan generation is now
``POST /plans``, which accepts an optional ``profile`` field carrying the
full :class:`OnboardingRequest`. The iOS happy path on the last
onboarding screen calls ``POST /plans`` directly with the profile
payload — one HTTP round-trip persists profile + goals + enqueues the
plan atomically. ``POST /me/onboarding`` stays as a profile-only save
for clients that want to decouple profile updates from plan generation.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, status
from sqlalchemy import text

from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.nutrition.infrastructure.compute_goals_adapter import InlineComputeGoals
from app.profile.application.use_cases import (
    CompleteOnboarding,
    GetProfile,
    UpdateLocale,
    UpdateProfile,
)
from app.profile.domain.entities import UserProfile
from app.profile.infrastructure.region_audit import SqlRegionAudit
from app.profile.infrastructure.repositories import SqlProfileRepository
from app.profile.presentation.schemas import (
    LocalePatch,
    LocaleResponse,
    OnboardingRequest,
    PlanJobInfo,
    ProfilePatch,
    ProfileResponse,
    WeightGoalResponse,
)
from app.shared.i18n import LocaleDep
from app.shared.i18n.fastapi_dep import locale_cache_invalidate

_log = get_logger("profile.router")

router = APIRouter(tags=["profile"])


def _display_fields(p: UserProfile) -> dict:
    """Compute pre-converted display values based on the user's unit preference."""
    if p.units == "imperial":
        weight_display = (
            (p.weight_kg / Decimal("0.45359237")).quantize(Decimal("0.1"))
            if p.weight_kg is not None
            else None
        )
        if p.height_cm is not None:
            total_inches = p.height_cm / Decimal("2.54")
            ft = int(total_inches // 12)
            inch = int(total_inches % 12)
        else:
            ft = inch = None
        return {
            "weight_display": weight_display,
            "weight_unit": "lb",
            "height_display_primary": ft,
            "height_display_secondary": inch,
            "height_unit": "ft_in",
        }
    # metric
    return {
        "weight_display": p.weight_kg,
        "weight_unit": "kg",
        "height_display_primary": int(p.height_cm) if p.height_cm is not None else None,
        "height_display_secondary": None,
        "height_unit": "cm",
    }


def _to_resp(
    p: UserProfile,
    *,
    plan_job: PlanJobInfo | None = None,
    starting_weight_kg: float | None = None,
    onboarding_completed: bool | None = None,
) -> ProfileResponse:
    return ProfileResponse(
        user_id=p.user_id,
        name=p.name,
        age=p.age,
        sex=p.sex,
        units=p.units,
        weight_kg=float(p.weight_kg) if p.weight_kg is not None else None,
        height_cm=float(p.height_cm) if p.height_cm is not None else None,
        goal_weight_kg=float(p.goal_weight_kg) if p.goal_weight_kg is not None else None,
        starting_weight_kg=starting_weight_kg,
        **_display_fields(p),
        goal=p.goal,
        activity_level=p.activity_level,
        dietary_pattern=p.dietary_pattern,
        bodyfat_pct=float(p.bodyfat_pct) if p.bodyfat_pct is not None else None,
        trimester=p.trimester,
        is_exclusively_breastfeeding=p.is_exclusively_breastfeeding,
        medical_conditions=p.medical_conditions,
        other_condition=p.other_condition,
        allergies=p.allergies,
        other_allergy=p.other_allergy,
        country=p.country,
        region=p.region,
        locale=p.locale,
        # BE-1 consistency: callers may pass a freshly recomputed value
        # (profile + ≥1 plan) so GET /me agrees with the auth responses;
        # falls back to the cached column when not provided.
        onboarding_completed=(
            p.onboarding_completed
            if onboarding_completed is None
            else onboarding_completed
        ),
        updated_at=p.updated_at,
        plan_job=plan_job,
    )


@router.get("/me", response_model=ProfileResponse)
async def get_me(current_user: CurrentUserDep, session: SessionDep) -> ProfileResponse:
    uc = GetProfile(profiles=SqlProfileRepository(session))
    profile = await uc(user_id=current_user)
    row = (
        await session.execute(
            text(
                "SELECT weight_kg FROM weight_logs"
                " WHERE user_id = :uid ORDER BY time ASC LIMIT 1"
            ),
            {"uid": current_user},
        )
    ).one_or_none()
    starting = float(row.weight_kg) if row and row.weight_kg is not None else None
    # Fall back to onboarding weight if no log exists yet.
    if starting is None and profile and profile.weight_kg is not None:
        starting = float(profile.weight_kg)
    # BE-1: recompute onboarding_completed LIVE (profile + ≥1 plan) so GET /me
    # never disagrees with the auth responses. Matches identity's canonical def.
    has_plan = (
        await session.execute(
            text("SELECT EXISTS(SELECT 1 FROM plans WHERE user_id = :uid)"),
            {"uid": current_user},
        )
    ).scalar()
    onboarding_completed = profile is not None and bool(has_plan)
    return _to_resp(
        profile, starting_weight_kg=starting, onboarding_completed=onboarding_completed
    )


@router.patch("/me", response_model=ProfileResponse)
async def patch_me(
    body: ProfilePatch,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProfileResponse:
    bus = get_event_bus()
    uc = UpdateProfile(
        profiles=SqlProfileRepository(session),
        bus=bus,
        compute_goals=InlineComputeGoals(session=session, bus=bus),
        region_audit=SqlRegionAudit(session=session),
    )
    patch = body.model_dump(exclude_unset=True)
    result = _to_resp(await uc(user_id=current_user, patch=patch))
    if "locale" in patch:
        await locale_cache_invalidate(current_user)
    return result


@router.post("/me/onboarding", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def onboarding(
    body: OnboardingRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    locale: LocaleDep,  # noqa: ARG001 — kept for symmetric API surface
) -> ProfileResponse:
    """Profile + nutritional-goals upsert. **Does not** enqueue a plan.

    Plan generation lives exclusively in ``POST /plans`` (see module
    docstring). The legacy ``plan_job`` field stays in the response
    schema set to ``None`` for backward compatibility with clients
    that already deserialise it.
    """
    bus = get_event_bus()
    uc = CompleteOnboarding(
        profiles=SqlProfileRepository(session),
        bus=bus,
        compute_goals=InlineComputeGoals(session=session, bus=bus),
    )
    # Normalize height: meters → cm if mobile sent height_m.
    payload = body.model_dump(exclude_none=False)
    payload["height_cm"] = body.resolved_height_cm
    payload.pop("height_m", None)
    profile = await uc(user_id=current_user, payload=payload)
    return _to_resp(profile, plan_job=None)


@router.get("/me/locale", response_model=LocaleResponse)
async def get_locale(current_user: CurrentUserDep, session: SessionDep) -> LocaleResponse:
    uc = GetProfile(profiles=SqlProfileRepository(session))
    p = await uc(user_id=current_user)
    return LocaleResponse(locale=p.locale)


@router.patch("/me/locale", response_model=LocaleResponse)
async def patch_locale(
    body: LocalePatch,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> LocaleResponse:
    uc = UpdateLocale(profiles=SqlProfileRepository(session))
    p = await uc(user_id=current_user, locale=body.locale)
    return LocaleResponse(locale=p.locale)


@router.get("/me/weight-goal", response_model=WeightGoalResponse)
async def get_weight_goal(current_user: CurrentUserDep, session: SessionDep) -> WeightGoalResponse:
    """Consolidated weight goal + actual progress + ideal weight view.

    Wires together:
      - Peterson 2016 IBW + WHO BMI range (ideal_weight.py)
      - OLS 14d slope from weight_logs (weight_progress.py)
      - Plan deficit projection (weight_projection.py)
      - goal_weight_kg from user_profiles
    Zero new DB tables — reads only existing rows.
    """
    import math
    from decimal import Decimal

    from app.nutrition.domain.ideal_weight import compute_weight_insights
    from app.nutrition.domain.weight_progress import compute_weight_progress
    from app.nutrition.domain.weight_projection import expected_weekly_change
    from app.shared.domain.time import utc_day_index

    # ── 1. Profile ───────────────────────────────────────────────────────────
    profile_uc = GetProfile(profiles=SqlProfileRepository(session))
    profile = await profile_uc(user_id=current_user)
    if profile is None:
        from app.core.errors import NotFoundError
        raise NotFoundError("profile_not_found")

    weight_kg_profile = profile.weight_kg          # onboarding snapshot
    height_cm = profile.height_cm
    sex = profile.sex or "male"
    goal = profile.goal or "maintain"
    goal_weight_kg = profile.goal_weight_kg        # may be None

    # ── 2. Weight logs — current, starting, 14d series ───────────────────────
    rows_14d = (
        await session.execute(
            text(
                """
        SELECT time, weight_kg FROM weight_logs
         WHERE user_id = :uid
           AND time >= now() - INTERVAL '14 days'
         ORDER BY time ASC
        """
            ),
            {"uid": str(current_user)},
        )
    ).all()

    row_first = (
        await session.execute(
            text(
                "SELECT weight_kg FROM weight_logs"
                " WHERE user_id = :uid ORDER BY time ASC LIMIT 1"
            ),
            {"uid": str(current_user)},
        )
    ).first()

    row_latest = (
        await session.execute(
            text(
                "SELECT weight_kg FROM weight_logs"
                " WHERE user_id = :uid ORDER BY time DESC LIMIT 1"
            ),
            {"uid": str(current_user)},
        )
    ).first()

    # T-11: latest waist measurement (waist_cm column already exists in weight_logs)
    row_waist = (
        await session.execute(
            text(
                "SELECT waist_cm, time::date FROM weight_logs"
                " WHERE user_id = :uid AND waist_cm IS NOT NULL"
                " ORDER BY time DESC LIMIT 1"
            ),
            {"uid": str(current_user)},
        )
    ).first()

    current_weight = (
        Decimal(str(row_latest[0])) if row_latest else weight_kg_profile
    )
    starting_weight = (
        Decimal(str(row_first[0])) if row_first else weight_kg_profile
    )

    # ── 3. TDEE + plan kcal_target ───────────────────────────────────────────
    goal_row = (
        await session.execute(
            text(
                """
        SELECT kcal_min, kcal_max FROM nutritional_goals
         WHERE user_id = :uid AND valid_to IS NULL LIMIT 1
        """
            ),
            {"uid": str(current_user)},
        )
    ).first()

    plan_row = (
        await session.execute(
            text(
                """
        SELECT kcal_target FROM plans
         WHERE user_id = :uid::uuid AND status = 'active' LIMIT 1
        """
            ),
            {"uid": str(current_user)},
        )
    ).first()

    tdee_kcal: int | None = None
    weekly_projected_kg: float | None = None
    weeks_to_goal: int | None = None

    if goal_row and plan_row and plan_row[0]:
        kcal_target = int(plan_row[0])
        # TDEE estimated as midpoint of goal range (pre-deficit/surplus target)
        tdee_kcal = (int(goal_row[0]) + int(goal_row[1])) // 2
        proj = expected_weekly_change(kcal_target=kcal_target, tdee=tdee_kcal)
        weekly_projected_kg = float(proj.weekly_kg)
        if (
            goal_weight_kg is not None
            and current_weight is not None
            and weekly_projected_kg != 0
        ):
            delta = float(goal_weight_kg - current_weight)
            if abs(weekly_projected_kg) > 0.001:
                weeks_raw = abs(delta / weekly_projected_kg)
                weeks_to_goal = math.ceil(weeks_raw) if weeks_raw < 1000 else None

    # ── 4. OLS progress (weight_progress.py) ────────────────────────────────
    weight_series: list[tuple[int, float]] = [
        (utc_day_index(r[0]), float(r[1])) for r in rows_14d
    ]
    weight_to_lose: Decimal | None = None
    if goal_weight_kg is not None and current_weight is not None:
        diff = current_weight - goal_weight_kg
        weight_to_lose = diff if diff > 0 else None  # only positive = still to lose

    progress = compute_weight_progress(
        weights=weight_series,
        weight_to_lose_kg=weight_to_lose,
        goal=goal,
    )

    # ── 5. Ideal weight + BMI (ideal_weight.py) ──────────────────────────────
    insights = None
    if current_weight and height_cm:
        insights = compute_weight_insights(
            weight_kg=current_weight,
            height_cm=height_cm,
            sex=sex,
            goal=goal,
        )

    # ── 6. Progress toward user's declared goal ───────────────────────────────
    delta_kg: float | None = None
    lost_so_far_kg: float | None = None
    progress_pct: float | None = None
    weight_loss_milestone: str | None = None

    if goal_weight_kg is not None and current_weight is not None:
        delta_kg = round(float(goal_weight_kg - current_weight), 2)
        if starting_weight is not None:
            # Distance from starting to current (unsigned) — usable regardless of goal direction
            distance_from_start = abs(float(starting_weight - current_weight))
            lost_so_far_kg = round(distance_from_start, 2)
            total_to_change = abs(float(starting_weight - goal_weight_kg))
            if total_to_change > 0:
                progress_pct = round(min(100.0, (distance_from_start / total_to_change) * 100), 1)

            # Milestone: % of starting body weight LOST — weight_loss goal only,
            # and only when current weight is genuinely below starting (not a gain).
            # Uses Decimal comparison to avoid float precision issues.
            if goal == "weight_loss" and starting_weight > current_weight:
                weight_lost_pct = float(starting_weight - current_weight) / float(starting_weight) * 100
                if weight_lost_pct >= 20:
                    weight_loss_milestone = "20%"
                elif weight_lost_pct >= 15:
                    weight_loss_milestone = "15%"
                elif weight_lost_pct >= 10:
                    weight_loss_milestone = "10%"
                elif weight_lost_pct >= 5:
                    weight_loss_milestone = "5%"

    # ── 7. Status ─────────────────────────────────────────────────────────────
    vs = progress.vs_plan
    recal = False
    if vs == "behind" and progress.weight_points >= 7:
        recal = True

    if vs in ("on_track", "ahead", "behind", "maintain"):
        status_str = vs
    else:
        status_str = "no_data"

    return WeightGoalResponse(
        current_weight_kg=float(current_weight) if current_weight else None,
        goal_weight_kg=float(goal_weight_kg) if goal_weight_kg else None,
        starting_weight_kg=float(starting_weight) if starting_weight else None,
        ideal_weight_kg=float(insights.peterson_ideal_kg) if insights else None,
        ideal_weight_min_kg=float(insights.ideal_weight_min_kg) if insights else None,
        ideal_weight_max_kg=float(insights.ideal_weight_max_kg) if insights else None,
        bmi=float(insights.bmi) if insights else None,
        bmi_category=insights.bmi_category if insights else None,
        obesity_grade=insights.obesity_grade if insights else None,
        delta_kg=delta_kg,
        lost_so_far_kg=lost_so_far_kg,
        progress_pct=progress_pct,
        weight_loss_milestone=weight_loss_milestone,
        waist_cm=float(row_waist[0]) if row_waist else None,
        last_waist_date=str(row_waist[1]) if row_waist else None,
        weekly_projected_kg=weekly_projected_kg,
        weeks_to_goal=weeks_to_goal,
        tdee_kcal=tdee_kcal,
        actual_weekly_kg=float(progress.slope_kg_per_week) if progress.slope_kg_per_week is not None else None,
        trend_label=progress.trend_label,
        vs_plan=progress.vs_plan,
        weight_points_14d=progress.weight_points,
        status=status_str,
        recalibration_suggested=recal,
    )
