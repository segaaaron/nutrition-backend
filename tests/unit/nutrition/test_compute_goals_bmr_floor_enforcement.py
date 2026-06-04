"""H1.4 — `compute_initial_goals` must REFUSE to produce a plan whose
kcal_target sits below the BMR * 0.9 safety floor (RED-S risk per
AND/ACSM/Dietitians of Canada Joint Position 2016).

Prior behaviour: telemetry-only `_bmr_safety_warn` logged a warning but
the plan was still emitted with kcal_target clamped at the 800-kcal
hard floor. Profiles such as small female users on aggressive
weight_loss could land below the BMR * 0.9 floor and the system would
still write the goals row.

New contract: raise `BmrSafetyFloorViolated` (DomainError, 422). The
warning helper remains as defense-in-depth telemetry.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import EventBus  # noqa: F401  (typing only)
from app.nutrition.application.use_cases import (
    ComputeInitialGoals,
)
from app.nutrition.domain.errors import BmrSafetyFloorViolated
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


def _bio(
    *,
    sex: str = "female",
    weight_kg: Decimal = Decimal("45"),
    height_cm: Decimal = Decimal("155"),
    age: int = 25,
    goal: str = "weight_loss",
    activity_level: str = "sedentary",
    conditions: frozenset[str] = frozenset(),
    trimester: str | None = None,
) -> dict[str, Any]:
    return {
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "age": age,
        "sex": sex,
        "goal": goal,
        "activity_level": activity_level,
        "conditions": conditions,
        "trimester": trimester,
    }


# ---------- Floor enforcement ---------------------------------------------


@pytest.mark.asyncio
async def test_small_female_weight_loss_raises_when_below_floor() -> None:
    """Small female on aggressive deficit lands below BMR*0.9.

    Mifflin(female, 40kg, 150cm, 22y) = 10*40 + 6.25*150 - 5*22 - 161
      = 400 + 937.5 - 110 - 161 = 1066.5 → 1066 (half-even)
    Sedentary AF 1.2 → TDEE ≈ 1279
    weight_loss cut = min(500, 25%*1279≈320) = 320 → kcal_target ≈ 959
    BMR floor = 1066 * 0.9 ≈ 959.4 → 959 < 959.4 → violation
    (margin is razor-thin; rounding may flip; use even smaller frame
    below to be unambiguous.)
    """
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(
            _bio(
                sex="female",
                weight_kg=Decimal("38"),
                height_cm=Decimal("150"),
                age=22,
                goal="weight_loss",
                activity_level="sedentary",
            )
        ),
        goals_repo=_StubGoalsRepo(),
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    with pytest.raises(BmrSafetyFloorViolated) as exc:
        await use_case(user_id=uuid4())
    # Extra carries kcal_target and floor for API problem+json payload.
    assert "kcal_target" in exc.value.extra
    assert "floor" in exc.value.extra
    assert exc.value.extra["kcal_target"] < exc.value.extra["floor"]


@pytest.mark.asyncio
async def test_normal_male_weight_loss_does_not_raise() -> None:
    """Happy path: standard adult male in deficit stays well above floor."""
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(
            _bio(
                sex="male",
                weight_kg=Decimal("80"),
                height_cm=Decimal("180"),
                age=30,
                goal="weight_loss",
                activity_level="moderately_active",
            )
        ),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    goals = await use_case(user_id=uuid4())
    assert goals is not None
    # Mifflin male 80/180/30 = 1780; *1.55 ≈ 2759; -500 = 2259; floor=1602 → safe.
    assert repo.last_written is not None


@pytest.mark.asyncio
async def test_maintain_goal_never_triggers_floor_violation() -> None:
    """maintain goal: kcal_target = TDEE = BMR * AF; AF ≥ 1.2 > 0.9 always safe."""
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(
            _bio(
                sex="female",
                weight_kg=Decimal("38"),
                height_cm=Decimal("150"),
                age=22,
                goal="maintain",
                activity_level="sedentary",
            )
        ),
        goals_repo=_StubGoalsRepo(),
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    goals = await use_case(user_id=uuid4())
    assert goals is not None


# ---------- Surplus reduces violation risk (interaction with Fix 2) -------


@pytest.mark.asyncio
async def test_lactation_surplus_lifts_target_above_floor() -> None:
    """If a small lactating female would violate the floor without the
    +500 lactation surplus, the surplus must be applied BEFORE the
    floor check so the plan can still be produced safely."""
    bio = _bio(
        sex="female",
        weight_kg=Decimal("38"),
        height_cm=Decimal("150"),
        age=22,
        goal="weight_loss",
        activity_level="sedentary",
        conditions=frozenset({"lactation"}),
    )
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(bio),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    goals = await use_case(user_id=uuid4())
    assert goals is not None  # +500 surplus pushed target above floor
