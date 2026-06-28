"""GetProfile returns a default shell for users without a profile row.

GET /me is called immediately after token issuance, before onboarding
completes.  Returning 404 here is wrong: the user resource exists (they
authenticated).  Instead GetProfile returns UserProfile(user_id=...) with
onboarding_completed=False and all optional fields null so iOS/Android can
render the onboarding form without treating the response as an error.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.profile.application.use_cases import GetProfile
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


@pytest.mark.asyncio
async def test_get_profile_no_profile_returns_default_shell() -> None:
    user_id = uuid4()
    uc = GetProfile(profiles=_Repo())

    result = await uc(user_id=user_id)

    assert result.user_id == user_id
    assert result.onboarding_completed is False
    assert result.name is None
    assert result.age is None
    assert result.sex is None
    assert result.weight_kg is None
    assert result.height_cm is None
    assert result.goal is None
    assert result.activity_level is None
    assert result.medical_conditions == []
    assert result.allergies == []
    assert result.updated_at is None


@pytest.mark.asyncio
async def test_get_profile_existing_profile_returned_unchanged() -> None:
    user_id = uuid4()
    seeded = UserProfile(
        user_id=user_id,
        name="Miguel",
        age=41,
        sex="male",
        onboarding_completed=True,
    )
    uc = GetProfile(profiles=_Repo(seeded=seeded))

    result = await uc(user_id=user_id)

    assert result is seeded
    assert result.onboarding_completed is True
    assert result.name == "Miguel"
