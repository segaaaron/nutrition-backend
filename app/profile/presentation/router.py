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
