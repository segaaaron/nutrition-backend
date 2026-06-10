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

from fastapi import APIRouter, status

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

_log = get_logger("profile.router")

router = APIRouter(tags=["profile"])


def _to_resp(p: UserProfile, *, plan_job: PlanJobInfo | None = None) -> ProfileResponse:
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
        onboarding_completed=p.onboarding_completed,
        updated_at=p.updated_at,
        plan_job=plan_job,
    )


@router.get("/me", response_model=ProfileResponse)
async def get_me(current_user: CurrentUserDep, session: SessionDep) -> ProfileResponse:
    uc = GetProfile(profiles=SqlProfileRepository(session))
    return _to_resp(await uc(user_id=current_user))


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
    return _to_resp(await uc(user_id=current_user, patch=patch))


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
