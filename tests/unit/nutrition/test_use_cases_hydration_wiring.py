"""D1 — `conditions` from ProfileReader feeds `compute_water_ml`.

Without this wiring, CKD/CHF users still receive 2500-3500 mL targets
even though hydration.py knows how to cap to 1500 mL — the cap was simply
never reached because the call site dropped the kwarg.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.nutrition.application.use_cases import (
    ComputeInitialGoals,
)
from app.nutrition.domain.hydration import CKD_FLUID_CAP_ML
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


def _bio(*, conditions: frozenset[str] = frozenset()) -> dict[str, Any]:
    return {
        "weight_kg": Decimal("100"),
        "height_cm": Decimal("180"),
        "age": 40,
        "sex": "male",
        "goal": "maintain",
        "activity_level": "moderately_active",
        "conditions": conditions,
    }


@pytest.mark.asyncio
async def test_ckd_user_water_capped_via_use_case() -> None:
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(_bio(conditions=frozenset({"ckd"}))),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    goals = await use_case(user_id=uuid4())
    assert goals.water_ml <= CKD_FLUID_CAP_ML
    assert goals.water_ml == 1500


@pytest.mark.asyncio
async def test_no_condition_user_water_not_capped() -> None:
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(_bio()),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    goals = await use_case(user_id=uuid4())
    # 100 kg * 35 = 3500 base + 700 (1.55 step) = 4200, within [1500, 5000].
    assert goals.water_ml > CKD_FLUID_CAP_ML


@pytest.mark.asyncio
async def test_missing_conditions_key_treated_as_empty() -> None:
    """Backward compat — a ProfileReader that omits `conditions` must not crash."""
    bio = _bio()
    bio.pop("conditions")
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(bio),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    goals = await use_case(user_id=uuid4())
    assert goals.water_ml > 0
