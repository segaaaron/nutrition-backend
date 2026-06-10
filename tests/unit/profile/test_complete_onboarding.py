"""ADR-0028 — CompleteOnboarding no longer flips onboarding_completed.

Pre-ADR-0028: `/me/onboarding` set the flag to True directly.
Post-ADR-0028: flag is flipped only on PlanCreated.

Tests:
  - First-time onboarding leaves flag = False.
  - Re-onboarding of a user whose flag was already True (plan generated
    previously, then user re-runs the form to edit fields) PRESERVES True
    (no regression to False).
  - OnboardingCompleted + BiometricsChanged domain events still publish.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import DomainEvent, EventBus
from app.profile.application.use_cases import CompleteOnboarding
from app.profile.domain.entities import UserProfile
from app.profile.domain.events import BiometricsChanged, OnboardingCompleted


class _Repo:
    def __init__(self, seeded: UserProfile | None = None) -> None:
        self.store: dict[UUID, UserProfile] = (
            {seeded.user_id: seeded} if seeded else {}
        )

    async def get(self, user_id: UUID) -> UserProfile | None:
        return self.store.get(user_id)

    async def upsert(self, profile: UserProfile) -> None:
        self.store[profile.user_id] = profile


class _SpyBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)
        await super().publish(event)


def _payload(**overrides: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "age": 30,
        "sex": "male",
        "weight_kg": Decimal("72.0"),
        "height_cm": Decimal("175"),
        "goal": "weight_loss",
        "activity_level": "moderately_active",
        "dietary_pattern": "omnivore",
    }
    p.update(overrides)
    return p


@pytest.mark.asyncio
async def test_first_onboarding_leaves_flag_false() -> None:
    repo = _Repo()
    bus = _SpyBus()
    uc = CompleteOnboarding(profiles=repo, bus=bus)

    result = await uc(user_id=uuid4(), payload=_payload())

    assert result.onboarding_completed is False


@pytest.mark.asyncio
async def test_reonboarding_preserves_existing_true_flag() -> None:
    user_id = uuid4()
    existing = UserProfile(
        user_id=user_id,
        age=30,
        sex="male",
        weight_kg=Decimal("70"),
        height_cm=Decimal("175"),
        goal="weight_loss",
        activity_level="moderately_active",
        dietary_pattern="omnivore",
        onboarding_completed=True,  # plan was created previously
    )
    repo = _Repo(existing)
    uc = CompleteOnboarding(profiles=repo, bus=_SpyBus())

    # User re-runs onboarding to edit weight; flag MUST stay True.
    result = await uc(user_id=user_id, payload=_payload(weight_kg=Decimal("68.0")))

    assert result.onboarding_completed is True
    assert result.weight_kg == Decimal("68.0")


@pytest.mark.asyncio
async def test_publishes_onboarding_and_biometrics_events() -> None:
    repo = _Repo()
    bus = _SpyBus()
    uc = CompleteOnboarding(profiles=repo, bus=bus)

    await uc(user_id=uuid4(), payload=_payload())

    types = {type(e) for e in bus.published}
    assert OnboardingCompleted in types
    assert BiometricsChanged in types


class _SpyComputeGoals:
    """Records every invocation; lets us assert ordering vs persistence."""

    def __init__(self, repo: _Repo) -> None:
        self.calls: list[UUID] = []
        self.repo = repo
        self.profile_visible_at_call: list[bool] = []

    async def __call__(self, *, user_id: UUID) -> None:
        # When the inline port runs, the profile upsert must already
        # be visible in the repo — this is what guarantees that the
        # nutritional baseline can read a complete biometrics row from
        # the same transaction.
        self.calls.append(user_id)
        self.profile_visible_at_call.append(user_id in self.repo.store)


@pytest.mark.asyncio
async def test_compute_goals_called_in_same_tx_as_profile_upsert() -> None:
    """The fix for the empty-plan_meals bug: ComputeInitialGoals must
    run AFTER profile.upsert (so SqlProfileReader sees the row) and
    BEFORE event publishing (so any post-publish subscribers find the
    goals already persisted). Crucially, both must commit atomically
    under the same outer session_scope/get_session — verified at the
    use-case layer by ensuring the port runs while we hold the same
    in-memory repo state.
    """
    repo = _Repo()
    bus = _SpyBus()
    spy = _SpyComputeGoals(repo)
    uc = CompleteOnboarding(profiles=repo, bus=bus, compute_goals=spy)

    user_id = uuid4()
    await uc(user_id=user_id, payload=_payload())

    assert spy.calls == [user_id]
    assert spy.profile_visible_at_call == [True]


@pytest.mark.asyncio
async def test_compute_goals_failure_propagates_so_router_rolls_back() -> None:
    """If goals computation fails, the onboarding must raise so the
    SessionDep teardown rolls back the profile upsert — preventing the
    "profile saved, goals missing" inconsistency that caused empty
    plan_meals downstream.
    """

    class _ExplodingComputeGoals:
        async def __call__(self, *, user_id: UUID) -> None:
            raise RuntimeError("simulated_failure")

    repo = _Repo()
    bus = _SpyBus()
    uc = CompleteOnboarding(
        profiles=repo, bus=bus, compute_goals=_ExplodingComputeGoals()
    )

    with pytest.raises(RuntimeError, match="simulated_failure"):
        await uc(user_id=uuid4(), payload=_payload())

    # No BiometricsChanged should have been published — events ship
    # AFTER goals computation succeeds.
    assert all(type(e) is not BiometricsChanged for e in bus.published)
    assert all(type(e) is not OnboardingCompleted for e in bus.published)
