"""Profile use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

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


class ProfileRepository(Protocol):
    async def get(self, user_id: UUID) -> UserProfile | None: ...
    async def upsert(self, profile: UserProfile) -> None: ...


class ComputeGoalsPort(Protocol):
    """Profile-owned port for computing nutritional baseline goals.

    Implemented in `app.nutrition.infrastructure` as a thin adapter that
    invokes `ComputeInitialGoals` on the SAME session as the profile
    upsert, so onboarding/profile-update + goals creation commit
    atomically (fixes the cross-session race where the post-commit
    event handler read profile rows that did not yet exist).
    """

    async def __call__(self, *, user_id: UUID) -> None: ...


class RegionAuditPort(Protocol):
    """Profile-owned port for the 30-day region-change lock audit.

    Adapter MUST run on the SAME session as the profile upsert. The
    previous implementation opened a nested ``session_scope()`` which
    committed independently from the outer request transaction — if the
    outer rolled back, the audit row remained orphan; if the audit
    committed but the outer raised after, the audit lied. Atomicity is
    a correctness invariant for the spoof-proofing audit (ADR-0026 L1).
    """

    async def last_change_at(self, user_id: UUID) -> datetime | None: ...

    async def record_change(
        self,
        *,
        user_id: UUID,
        old_region: str | None,
        new_region: str | None,
        changed_at: datetime,
    ) -> None: ...


_BIOMETRIC_FIELDS = ("weight_kg", "height_cm", "age", "sex", "goal", "activity_level")


@dataclass(slots=True)
class CompleteOnboarding:
    profiles: ProfileRepository
    bus: EventBus
    compute_goals: ComputeGoalsPort | None = None

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
        # Clinical safety net: celiac users MUST exclude gluten. If the iOS
        # client forgot to auto-add the "gluten" allergen when toggling the
        # "Celiaquía" chip, backend enforces the invariant server-side.
        # Without this, a celiac user could receive a plan with gluten-bearing
        # recipes — real clinical risk. Idempotent (set semantics).
        if profile.medical_conditions and "celiac" in profile.medical_conditions:
            allergies = list(profile.allergies or [])
            if "gluten" not in allergies:
                profile.allergies = sorted(set(allergies) | {"gluten"})
                _log.info(
                    "onboarding.celiac_auto_gluten_added",
                    user_id=str(user_id),
                )
        if profile.country:
            profile.region = country_to_region(profile.country)
            if not payload.get("locale"):
                profile.locale = country_to_locale(profile.country)
        if not profile.is_complete_enough_for_targets:
            raise BusinessRuleViolation("onboarding_incomplete")
        # D5 (ADR-0028): flag flip moved to PlanCreated event handler.
        # Preserve the existing value so a user re-running onboarding
        # after a plan was generated does NOT regress to False.
        # (No explicit assignment: profile.onboarding_completed retains
        # its prior value — False on first call, True if PlanCreated
        # has already fired.)
        profile.updated_at = _now()
        await self.profiles.upsert(profile)
        # Compute nutritional baseline inline, in the SAME session, BEFORE
        # publishing domain events. This guarantees that by the time the
        # router commits, both `user_profiles` AND `nutritional_goals`
        # rows exist atomically. The previous design relied on a
        # post-publish BiometricsChanged handler running on its own
        # session, which read the profile BEFORE the outer transaction
        # committed and silently logged `profile_not_found` — leaving
        # users with onboarding done but no goals, which in turn caused
        # `POST /plans` to produce empty `plan_meals`. Best-effort
        # logging is preserved (no raise) so users with partial
        # biometrics still complete onboarding. Required full biometrics
        # are already enforced above by `is_complete_enough_for_targets`.
        if self.compute_goals is not None:
            try:
                await self.compute_goals(user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                # Fail loud: if onboarding declared biometrics complete
                # but goals computation fails, the request must surface
                # the error rather than silently leaving the user in a
                # broken state. The outer router transaction will
                # roll back (no profile upsert visible to clients).
                _log.error(
                    "compute_initial_goals_failed",
                    user_id=str(user_id),
                    error=str(exc),
                )
                raise
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
    compute_goals: ComputeGoalsPort | None = None
    region_audit: RegionAuditPort | None = None

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
        # Clinical safety net (parity with CompleteOnboarding): if the patch
        # leaves the user marked celiac, ensure gluten is in the allergens
        # set. Prevents PATCH /me from regressing a celiac user into a
        # gluten-exposed plan.
        if profile.medical_conditions and "celiac" in profile.medical_conditions:
            allergies = list(profile.allergies or [])
            if "gluten" not in allergies:
                profile.allergies = sorted(set(allergies) | {"gluten"})
                _log.info(
                    "profile_update.celiac_auto_gluten_added",
                    user_id=str(user_id),
                )

        # ADR-0026 L1 — region pinning. A 30-day lock on region changes
        # closes the small-country leaderboard spoofing vector. Audit
        # row is the source of truth (not profile.updated_at, which
        # bumps on any field change).
        region_changed = (
            region_after is not None and region_after != region_before
        )
        if region_changed:
            # Patrón #3 fix: previously opened a nested `session_scope()`
            # which committed the audit row independently of the outer
            # request transaction. That caused two failure modes:
            #   (a) outer rolls back → audit row remains orphan, audit
            #       trail lies about a change that never persisted.
            #   (b) outer raises after audit insert → same orphan row.
            # Both compromise the spoof-proofing audit (ADR-0026 L1).
            # The `region_audit` port now runs on the SAME session as
            # the profile upsert, so the audit row and the profile row
            # commit (or roll back) atomically.
            if self.region_audit is None:
                # Defensive: keep the lock enforceable even if the
                # adapter was not wired (older call sites). Without an
                # adapter we cannot read prior history nor record a
                # row, so we MUST refuse the region change to preserve
                # the audit invariant.
                raise BusinessRuleViolation("region_audit_unavailable")
            last_change = await self.region_audit.last_change_at(user_id)
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
            await self.region_audit.record_change(
                user_id=user_id,
                old_region=region_before,
                new_region=region_after,
                changed_at=_now(),
            )

        biometrics_after = {f: getattr(profile, f) for f in _BIOMETRIC_FIELDS}
        profile.updated_at = _now()
        await self.profiles.upsert(profile)
        # Same atomicity guarantee as CompleteOnboarding: recompute the
        # nutritional baseline INLINE when biometrics change so the new
        # `nutritional_goals` row commits with the profile mutation.
        # `ComputeInitialGoals` is idempotent across re-invocations
        # (expire current + insert new, no duplicate rows). When patch
        # leaves biometrics untouched, we skip to avoid spurious
        # baseline rewrites that would reset the recalibration history.
        if (
            biometrics_before != biometrics_after
            and self.compute_goals is not None
            and profile.is_complete_enough_for_targets
        ):
            try:
                await self.compute_goals(user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                _log.error(
                    "recompute_goals_on_update_failed",
                    user_id=str(user_id),
                    error=str(exc),
                )
                raise
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
        if locale not in ("en", "es"):
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
        # Return an empty shell for users who exist but haven't completed
        # onboarding yet. GET /me is called immediately after token issuance
        # before any profile data exists; returning 404 here is semantically
        # wrong (the authenticated user resource exists) and breaks iOS clients
        # that treat 404 as a hard error rather than "no profile yet".
        if profile is None:
            return UserProfile(user_id=user_id)
        return profile
