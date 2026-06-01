"""Profile FastAPI router (/me, /me/onboarding, /me/locale)."""
from __future__ import annotations

from fastapi import APIRouter, status

from app.core.event_bus import get_event_bus
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.profile.application.use_cases import (
    CompleteOnboarding,
    GetProfile,
    UpdateLocale,
    UpdateProfile,
)
from app.profile.domain.entities import UserProfile
from app.profile.infrastructure.repositories import SqlProfileRepository
from app.profile.presentation.schemas import (
    LocalePatch,
    LocaleResponse,
    OnboardingRequest,
    ProfilePatch,
    ProfileResponse,
)

router = APIRouter(tags=["profile"])


def _to_resp(p: UserProfile) -> ProfileResponse:
    return ProfileResponse(
        user_id=p.user_id, name=p.name, age=p.age, sex=p.sex,
        units=p.units, weight_kg=p.weight_kg, height_cm=p.height_cm,
        goal=p.goal, activity_level=p.activity_level,
        medical_conditions=p.medical_conditions, other_condition=p.other_condition,
        allergies=p.allergies, other_allergy=p.other_allergy,
        country=p.country, region=p.region, locale=p.locale,
        theme=p.theme, onboarding_completed=p.onboarding_completed,
        updated_at=p.updated_at,
    )


@router.get("/me", response_model=ProfileResponse)
async def get_me(current_user: CurrentUserDep, session: SessionDep) -> ProfileResponse:
    uc = GetProfile(profiles=SqlProfileRepository(session))
    return _to_resp(await uc(user_id=current_user))


@router.patch("/me", response_model=ProfileResponse)
async def patch_me(
    body: ProfilePatch, current_user: CurrentUserDep, session: SessionDep,
) -> ProfileResponse:
    uc = UpdateProfile(profiles=SqlProfileRepository(session), bus=get_event_bus())
    patch = body.model_dump(exclude_unset=True)
    return _to_resp(await uc(user_id=current_user, patch=patch))


@router.post("/me/onboarding", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def onboarding(
    body: OnboardingRequest, current_user: CurrentUserDep, session: SessionDep,
) -> ProfileResponse:
    uc = CompleteOnboarding(profiles=SqlProfileRepository(session), bus=get_event_bus())
    # Normalize height: meters → cm if mobile sent height_m.
    payload = body.model_dump(exclude_none=False)
    payload["height_cm"] = body.resolved_height_cm
    payload.pop("height_m", None)
    return _to_resp(await uc(user_id=current_user, payload=payload))


@router.get("/me/locale", response_model=LocaleResponse)
async def get_locale(current_user: CurrentUserDep, session: SessionDep) -> LocaleResponse:
    uc = GetProfile(profiles=SqlProfileRepository(session))
    p = await uc(user_id=current_user)
    return LocaleResponse(locale=p.locale)


@router.patch("/me/locale", response_model=LocaleResponse)
async def patch_locale(
    body: LocalePatch, current_user: CurrentUserDep, session: SessionDep,
) -> LocaleResponse:
    uc = UpdateLocale(profiles=SqlProfileRepository(session))
    p = await uc(user_id=current_user, locale=body.locale)
    return LocaleResponse(locale=p.locale)
