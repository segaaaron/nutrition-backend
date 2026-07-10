"""H1.4 — BMR * 0.9 safety floor for `compute_initial_goals`
(RED-S risk per AND/ACSM/Dietitians of Canada Joint Position 2016).

History:
  - v1: telemetry-only warn; aggressive flat −500 deficit could push small
    frames below the floor and still write the row (unsafe).
  - v2: raise `BmrSafetyFloorViolated` (422) when target < floor.
  - v3 (2026-07-09): goal adjustment capped at −min(500, 25% TDEE) via
    `apply_goal_to_tdee`. Capped weight_loss lands at 0.9*BMR (the floor)
    exactly at sedentary, never below — so the floor is now defense-in-depth,
    unreachable via the normal goal pipeline. The raise path stays covered
    directly at the pure-function level (test_bmr_safety / test_multi_condition).

These tests assert the v3 contract: the cap PROTECTS small frames (no 422),
and maintain/lactation paths stay above the floor.
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
async def test_small_female_weight_loss_capped_protects_floor() -> None:
    """Capped deficit PROTECTS small frames — it does NOT breach the floor.

    2026-07-09: goal adjustment wired to `apply_goal_to_tdee` (weight_loss =
    −min(500, 25% TDEE)). At sedentary this lands at 0.75*TDEE = 0.9*BMR =
    the floor exactly, never below. So a small female on aggressive
    weight_loss is no longer over-deficited into a 422 — the cap guarantees
    kcal_target ≥ floor.

    Mifflin(female, 45kg, 155cm, 25y) = 450 + 968.75 − 125 − 161 = 1132.75 → 1133
    Sedentary AF 1.2 → TDEE = 1360; cut = min(500, 25%*1360=340) = 340
    kcal_target = 1020; floor = 1133*0.9 = 1019.7 → 1020 ≥ floor → no raise.

    The floor's raise path is still covered directly at the pure-function
    level (test_bmr_safety.py / test_multi_condition.py) — after this fix it
    is defense-in-depth, unreachable via the normal goal pipeline.
    """
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(
            _bio(
                sex="female",
                weight_kg=Decimal("45"),
                height_cm=Decimal("155"),
                age=25,
                goal="weight_loss",
                activity_level="sedentary",
            )
        ),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    # Must NOT raise — the cap keeps the small female at/above the floor.
    goals = await use_case(user_id=uuid4())
    # kcal_target is the midpoint of the ±100 range (width 200 invariant).
    kcal_target = goals.kcal_min + 100
    floor = int(round(goals.bmr * 0.9))
    assert kcal_target >= floor, (
        f"capped weight_loss must not breach floor: {kcal_target} < {floor}"
    )
    # And the deficit must respect the 25% cap (never the old flat −500).
    assert goals.tdee - kcal_target <= round(0.25 * goals.tdee) + 1


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
