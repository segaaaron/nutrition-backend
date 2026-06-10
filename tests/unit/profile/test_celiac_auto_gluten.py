"""Celiac clinical safety net — backend auto-adds `gluten` to allergens.

The iOS chip "Celiaquía" SHOULD send both `medical_conditions=["celiac"]`
and `allergies=["gluten"]`, but if the client forgets (or a partial PATCH
removes `gluten` while leaving the condition), the backend MUST enforce
the invariant. A celiac user receiving gluten-bearing recipes is a real
clinical risk, not a UX bug.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import EventBus
from app.profile.application.use_cases import CompleteOnboarding, UpdateProfile
from app.profile.domain.entities import UserProfile


class _Repo:
    def __init__(self, seeded: UserProfile | None = None) -> None:
        self.store: dict[UUID, UserProfile] = (
            {seeded.user_id: seeded} if seeded else {}
        )

    async def get(self, user_id: UUID) -> UserProfile | None:
        return self.store.get(user_id)

    async def upsert(self, profile: UserProfile) -> None:
        self.store[profile.user_id] = profile


def _payload(**overrides: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "age": 30,
        "sex": "female",
        "weight_kg": Decimal("65.0"),
        "height_cm": Decimal("165"),
        "goal": "maintain",
        "activity_level": "moderately_active",
        "dietary_pattern": "omnivore",
    }
    p.update(overrides)
    return p


@pytest.mark.asyncio
async def test_celiac_without_gluten_auto_adds_it() -> None:
    repo = _Repo()
    uc = CompleteOnboarding(profiles=repo, bus=EventBus())

    result = await uc(
        user_id=uuid4(),
        payload=_payload(medical_conditions=["celiac"], allergies=[]),
    )

    assert "celiac" in result.medical_conditions
    assert "gluten" in result.allergies


@pytest.mark.asyncio
async def test_celiac_with_gluten_already_does_not_duplicate() -> None:
    repo = _Repo()
    uc = CompleteOnboarding(profiles=repo, bus=EventBus())

    result = await uc(
        user_id=uuid4(),
        payload=_payload(
            medical_conditions=["celiac"], allergies=["gluten", "dairy"]
        ),
    )

    # Exactly one occurrence of gluten — set semantics, no duplicates.
    assert result.allergies.count("gluten") == 1
    assert "dairy" in result.allergies


@pytest.mark.asyncio
async def test_no_celiac_does_not_modify_allergies() -> None:
    repo = _Repo()
    uc = CompleteOnboarding(profiles=repo, bus=EventBus())

    result = await uc(
        user_id=uuid4(),
        payload=_payload(
            medical_conditions=["hypertension"], allergies=["dairy"]
        ),
    )

    assert "gluten" not in result.allergies
    assert result.allergies == ["dairy"]


@pytest.mark.asyncio
async def test_update_profile_celiac_auto_adds_gluten() -> None:
    """PATCH /me path also enforces the invariant — prevents regression
    where editing the profile drops gluten while leaving celiac set."""
    user_id = uuid4()
    existing = UserProfile(
        user_id=user_id,
        age=30,
        sex="female",
        weight_kg=Decimal("65"),
        height_cm=Decimal("165"),
        goal="maintain",
        activity_level="moderately_active",
        dietary_pattern="omnivore",
        medical_conditions=["celiac"],
        allergies=["gluten"],
    )
    repo = _Repo(existing)
    uc = UpdateProfile(profiles=repo, bus=EventBus())

    # Client tries to drop gluten while keeping celiac.
    result = await uc(user_id=user_id, patch={"allergies": ["dairy"]})

    assert "gluten" in result.allergies
    assert "dairy" in result.allergies
