"""Profile use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.core.config import get_settings
from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.event_bus import EventBus
from app.profile.domain.entities import UserProfile
from app.profile.domain.events import BiometricsChanged, OnboardingCompleted
from app.profile.domain.region_mapper import country_to_locale, country_to_region


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _enforce_mvp_segment_gate(profile: UserProfile) -> None:
    """Refuse profiles outside the safe MVP segment.

    Catalog audit 2026-06-01 found medical-risk gaps for diabetes_t2,
    pregnancy, lactation, ckd; algorithms lack condition macro overrides.
    US region disabled until catalog parched. Toggled via settings — disable
    the gate when catalog + algorithm work lands.
    """
    settings = get_settings()
    if not settings.mvp_segment_gate_enabled:
        return
    blocked_conditions = settings.mvp_blocked_conditions_set
    blocked_regions = settings.mvp_blocked_regions_set
    user_conditions = set(profile.medical_conditions or [])
    hit_conditions = sorted(user_conditions & blocked_conditions)
    if hit_conditions:
        raise BusinessRuleViolation(
            f"segment_unsupported_mvp:conditions:{','.join(hit_conditions)}"
        )
    if profile.region and profile.region in blocked_regions:
        raise BusinessRuleViolation(f"segment_unsupported_mvp:region:{profile.region}")


class ProfileRepository(Protocol):
    async def get(self, user_id: UUID) -> UserProfile | None: ...
    async def upsert(self, profile: UserProfile) -> None: ...


_BIOMETRIC_FIELDS = ("weight_kg", "height_cm", "age", "sex", "goal", "activity_level")


@dataclass(slots=True)
class CompleteOnboarding:
    profiles: ProfileRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID, payload: dict[str, Any]) -> UserProfile:
        existing = await self.profiles.get(user_id)
        profile = existing or UserProfile(user_id=user_id)

        for k, v in payload.items():
            if hasattr(profile, k):
                setattr(profile, k, v)
        if profile.country:
            profile.region = country_to_region(profile.country)
            if not payload.get("locale"):
                profile.locale = country_to_locale(profile.country)
        if not profile.is_complete_enough_for_targets:
            raise BusinessRuleViolation("onboarding_incomplete")
        _enforce_mvp_segment_gate(profile)
        profile.onboarding_completed = True
        profile.updated_at = _now()
        await self.profiles.upsert(profile)
        await self.bus.publish_many(
            [
                OnboardingCompleted(user_id=user_id, at=profile.updated_at),
                BiometricsChanged(
                    user_id=user_id,
                    weight_kg=profile.weight_kg,
                    height_cm=profile.height_cm,
                    age=profile.age,
                    sex=profile.sex,
                    goal=profile.goal,
                    activity_level=profile.activity_level,
                    at=profile.updated_at,
                ),
            ]
        )
        return profile


@dataclass(slots=True)
class UpdateProfile:
    profiles: ProfileRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID, patch: dict[str, Any]) -> UserProfile:
        profile = await self.profiles.get(user_id)
        if profile is None:
            raise NotFoundError("profile_not_found")
        biometrics_before = {f: getattr(profile, f) for f in _BIOMETRIC_FIELDS}
        for k, v in patch.items():
            if hasattr(profile, k):
                setattr(profile, k, v)
        if profile.country:
            profile.region = country_to_region(profile.country)
        biometrics_after = {f: getattr(profile, f) for f in _BIOMETRIC_FIELDS}
        _enforce_mvp_segment_gate(profile)
        profile.updated_at = _now()
        await self.profiles.upsert(profile)
        if biometrics_before != biometrics_after:
            await self.bus.publish(
                BiometricsChanged(
                    user_id=user_id,
                    weight_kg=profile.weight_kg,
                    height_cm=profile.height_cm,
                    age=profile.age,
                    sex=profile.sex,
                    goal=profile.goal,
                    activity_level=profile.activity_level,
                    at=profile.updated_at,
                )
            )
        return profile


@dataclass(slots=True)
class UpdateLocale:
    profiles: ProfileRepository

    async def __call__(self, *, user_id: UUID, locale: str) -> UserProfile:
        profile = await self.profiles.get(user_id)
        if profile is None:
            raise NotFoundError("profile_not_found")
        if locale not in ("en", "es", "pt", "fr", "de"):
            raise BusinessRuleViolation("unsupported_locale")
        profile.locale = locale
        profile.updated_at = _now()
        await self.profiles.upsert(profile)
        return profile


@dataclass(slots=True)
class GetProfile:
    profiles: ProfileRepository

    async def __call__(self, *, user_id: UUID) -> UserProfile:
        profile = await self.profiles.get(user_id)
        if profile is None:
            raise NotFoundError("profile_not_found")
        return profile
