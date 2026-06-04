"""H1.4 — Lactation + pregnancy energy surpluses must be applied to the
kcal_target itself during `compute_initial_goals`, not only as
downstream catalog-filter signals.

Sources:
- Lactation: IOM DRI for breastfeeding women, +500 kcal/day (months 0-6).
- Pregnancy: IOM DRI 2002 — T1 +0, T2 +340, T3 +452 kcal/day.

Order: lactation BEFORE pregnancy (defensive — mutually exclusive in
standard practice but both applied if both flags present), BOTH applied
BEFORE the BMR safety floor check so the floor evaluates the FINAL target.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.nutrition.application.use_cases import ComputeInitialGoals
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
    conditions: frozenset[str] = frozenset(),
    trimester: str | None = None,
    goal: str = "maintain",
) -> dict[str, Any]:
    return {
        "weight_kg": Decimal("65"),
        "height_cm": Decimal("165"),
        "age": 30,
        "sex": "female",
        "goal": goal,
        "activity_level": "lightly_active",
        "conditions": conditions,
        "trimester": trimester,
    }


async def _kcal_target_written(bio: dict[str, Any]) -> int:
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(bio),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    await use_case(user_id=uuid4())
    assert repo.last_written is not None
    # KcalRange is ±100 around kcal_target → midpoint == kcal_target.
    return (repo.last_written.kcal_min + repo.last_written.kcal_max) // 2


@pytest.mark.asyncio
async def test_lactation_adds_500_kcal() -> None:
    baseline = await _kcal_target_written(_bio())
    lact = await _kcal_target_written(_bio(conditions=frozenset({"lactation"})))
    assert lact - baseline == 500


@pytest.mark.asyncio
async def test_trimester_first_adds_zero() -> None:
    baseline = await _kcal_target_written(_bio(conditions=frozenset({"pregnancy"})))
    t1 = await _kcal_target_written(_bio(conditions=frozenset({"pregnancy"}), trimester="first"))
    assert t1 - baseline == 0


@pytest.mark.asyncio
async def test_trimester_second_adds_340_kcal() -> None:
    baseline = await _kcal_target_written(_bio(conditions=frozenset({"pregnancy"})))
    t2 = await _kcal_target_written(_bio(conditions=frozenset({"pregnancy"}), trimester="second"))
    assert t2 - baseline == 340


@pytest.mark.asyncio
async def test_trimester_third_adds_452_kcal() -> None:
    baseline = await _kcal_target_written(_bio(conditions=frozenset({"pregnancy"})))
    t3 = await _kcal_target_written(_bio(conditions=frozenset({"pregnancy"}), trimester="third"))
    assert t3 - baseline == 452


@pytest.mark.asyncio
async def test_lactation_plus_third_trimester_defensive_both_applied() -> None:
    """Mutually exclusive in standard practice, but if both flags are
    present the system applies both surpluses (defensive: never
    under-feed). Precedence documented: lactation applied first, then
    trimester surplus stacks."""
    baseline = await _kcal_target_written(_bio())
    both = await _kcal_target_written(
        _bio(conditions=frozenset({"lactation", "pregnancy"}), trimester="third")
    )
    assert both - baseline == 500 + 452


@pytest.mark.asyncio
async def test_missing_trimester_key_is_safe() -> None:
    """Backward compat: a ProfileReader that omits `trimester` must not crash."""
    bio = _bio()
    bio.pop("trimester", None)
    repo = _StubGoalsRepo()
    use_case = ComputeInitialGoals(
        profile_reader=_StubProfileReader(bio),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    goals = await use_case(user_id=uuid4())
    assert goals is not None
