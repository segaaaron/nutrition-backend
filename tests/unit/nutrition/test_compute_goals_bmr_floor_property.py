"""Property test: when `compute_initial_goals` returns goals successfully,
the written kcal_target ALWAYS sits at or above BMR * 0.9. Conversely,
if it raises, the would-be kcal_target was below the floor.

This pins the H1.4 invariant against any future refactor that might
silently drop the enforcement call.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.nutrition.application.use_cases import ComputeInitialGoals
from app.nutrition.domain.errors import BmrSafetyFloorViolated
from app.nutrition.domain.mifflin_st_jeor import mifflin_st_jeor
from app.nutrition.domain.state_machine import NutritionalGoals


class _StubProfileReader:
    def __init__(self, bio: dict[str, Any]) -> None:
        self._bio = bio

    async def biometrics(self, user_id: UUID) -> dict[str, Any] | None:
        return self._bio


class _StubGoalsRepo:
    def __init__(self) -> None:
        self.last_written: NutritionalGoals | None = None

    async def get_current(self, user_id: UUID) -> NutritionalGoals | None:
        return None

    async def list_history(self, user_id: UUID, limit: int) -> list[NutritionalGoals]:
        return []

    async def expire_current_and_insert(
        self,
        user_id: UUID,
        new_goals: NutritionalGoals,
    ) -> NutritionalGoals:
        self.last_written = new_goals
        return new_goals

    async def acquire_user_lock(self, user_id: UUID) -> None:  # pragma: no cover
        return None


class _StubBus:
    async def publish(self, event: Any) -> None:  # pragma: no cover
        return None

    def subscribe(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None


_PROFILES = st.fixed_dictionaries(
    {
        "weight_kg": st.decimals(
            min_value=Decimal("35"), max_value=Decimal("180"), places=1, allow_nan=False
        ),
        "height_cm": st.decimals(
            min_value=Decimal("140"), max_value=Decimal("210"), places=1, allow_nan=False
        ),
        "age": st.integers(min_value=18, max_value=80),
        "sex": st.sampled_from(["male", "female"]),
        "goal": st.sampled_from(
            ["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
        ),
        "activity_level": st.sampled_from(
            [
                "sedentary",
                "lightly_active",
                "moderately_active",
                "very_active",
                "extra_active",
            ]
        ),
    }
)


@given(profile=_PROFILES)
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_kcal_target_never_below_floor_or_raises(profile: dict[str, Any]) -> None:
    bio: dict[str, Any] = {
        **profile,
        "conditions": frozenset(),
        "trimester": None,
    }
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(bio),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    bmr = mifflin_st_jeor(
        weight_kg=profile["weight_kg"],
        height_cm=profile["height_cm"],
        age=profile["age"],
        sex=profile["sex"],
    )
    floor = bmr * Decimal("0.9")
    try:
        await use_case(user_id=uuid4())
    except BmrSafetyFloorViolated as exc:
        # Confirm the would-be kcal_target was indeed below the floor.
        assert Decimal(exc.extra["kcal_target"]) < floor
        return
    # Success path: written kcal_target (midpoint of ±100 range) ≥ floor.
    assert repo.last_written is not None
    kcal_target = (repo.last_written.kcal_min + repo.last_written.kcal_max) // 2
    assert Decimal(kcal_target) >= floor
