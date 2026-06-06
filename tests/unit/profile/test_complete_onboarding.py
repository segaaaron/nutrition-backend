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
