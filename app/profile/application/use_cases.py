"""Profile use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import BusinessRuleViolation, LockedError, NotFoundError
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.profile.domain.entities import UserProfile
from app.profile.domain.events import BiometricsChanged, OnboardingCompleted
from app.profile.domain.region_mapper import country_to_locale, country_to_region

_REGION_LOCK_DAYS = 30

_log = get_logger("profile.use_cases")


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
        # D1 (ADR-0028): iOS MVP onboarding does not ask dietary_pattern.
        # Default to omnivore + emit structured warning. PII-safe: only
        # user_id + goal are logged.
        if profile.dietary_pattern is None:
            profile.dietary_pattern = "omnivore"
            _log.warning(
                "dietary_pattern_defaulted_to_omnivore",
                user_id=str(user_id),
                goal=profile.goal,
            )
        if profile.country:
            profile.region = country_to_region(profile.country)
            if not payload.get("locale"):
                profile.locale = country_to_locale(profile.country)
        if not profile.is_complete_enough_for_targets:
            raise BusinessRuleViolation("onboarding_incomplete")
        _enforce_mvp_segment_gate(profile)
        # D5 (ADR-0028): flag flip moved to PlanCreated event handler.
        # Preserve the existing value so a user re-running onboarding
        # after a plan was generated does NOT regress to False.
        # (No explicit assignment: profile.onboarding_completed retains
        # its prior value — False on first call, True if PlanCreated
        # has already fired.)
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
        region_before = profile.region
        for k, v in patch.items():
            if hasattr(profile, k):
                setattr(profile, k, v)
        if profile.country:
            profile.region = country_to_region(profile.country)
        region_after = profile.region

        # ADR-0026 L1 — region pinning. A 30-day lock on region changes
        # closes the small-country leaderboard spoofing vector. Audit
        # row is the source of truth (not profile.updated_at, which
        # bumps on any field change).
        region_changed = (
            region_after is not None and region_after != region_before
        )
        if region_changed:
            from sqlalchemy import text as _sql_text

            async with session_scope() as audit_session:
                last_change = (
                    await audit_session.execute(
                        _sql_text(
                            """
                            SELECT changed_at FROM profile_region_change_audit
                             WHERE user_id = :uid
                             ORDER BY changed_at DESC LIMIT 1
                            """
                        ),
                        {"uid": str(user_id)},
                    )
                ).scalar()
                if last_change is not None:
                    elapsed = _now() - last_change
                    lock_window = timedelta(days=_REGION_LOCK_DAYS)
                    if elapsed < lock_window:
                        retry_after_s = int(
                            (lock_window - elapsed).total_seconds()
                        )
                        raise LockedError(
                            "region_change_locked",
                            retry_after=retry_after_s,
                            lock_days=_REGION_LOCK_DAYS,
                        )
                await audit_session.execute(
                    _sql_text(
                        """
                        INSERT INTO profile_region_change_audit
                            (user_id, old_region, new_region, changed_at)
                        VALUES (:uid, :old, :new, :ts)
                        """
                    ),
                    {
                        "uid": str(user_id),
                        "old": region_before,
                        "new": region_after,
                        "ts": _now(),
                    },
                )

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
