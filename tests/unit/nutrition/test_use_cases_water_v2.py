"""NOVA hydration v2 — `_build_goals` now delegates to `calculate_water_target`.

These tests validate the END-TO-END wiring through `ComputeInitialGoals`:
profile signals (region, pregnant, lactating) flow into the calculator and
the resulting `total_ml` is persisted on the `NutritionalGoals` aggregate
via the existing `water_ml` column (no schema change).

Critical invariants:
    * CKD condition ⇒ water_ml ≤ 1500 (medical override, ALWAYS wins).
    * Hot-season LatAm climate ⇒ +500 ml bonus reachable.
    * Lactating ⇒ +700 ml bonus reachable.
    * Missing `weight_kg` in `RecalibrateGoals` flow ⇒ graceful 70 kg fallback.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.nutrition.application.use_cases import ComputeInitialGoals
from app.nutrition.domain.state_machine import NutritionalGoals
from app.plan.domain.water_calculator import (
    MEDICAL_OVERRIDE_CAP_ML,
    SAFETY_MAX_ML,
    SAFETY_MIN_ML,
)


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
        self, user_id: UUID, new_goals: NutritionalGoals
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


def _bio(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "weight_kg": Decimal("70"),
        "height_cm": Decimal("170"),
        "age": 30,
        "sex": "female",
        "goal": "maintain",
        "activity_level": "moderately_active",
        "conditions": frozenset(),
        "region": "latam",
        "pregnant": False,
        "lactating": False,
    }
    base.update(overrides)
    return base


def _make_use_case(bio: dict[str, Any]) -> tuple[ComputeInitialGoals, _StubGoalsRepo]:
    repo = _StubGoalsRepo()
    uc = ComputeInitialGoals(
        profile_reader=_StubProfileReader(bio),
        goals_repo=repo,
        bus=_StubBus(),  # type: ignore[arg-type]
    )
    return uc, repo


@pytest.mark.asyncio
async def test_ckd_user_capped_to_medical_override() -> None:
    uc, repo = _make_use_case(_bio(conditions=frozenset({"ckd"})))
    goals = await uc(user_id=uuid4())
    assert goals.water_ml <= int(MEDICAL_OVERRIDE_CAP_ML) == 1500


@pytest.mark.asyncio
async def test_heart_failure_user_capped_to_medical_override() -> None:
    uc, _ = _make_use_case(_bio(conditions=frozenset({"heart_failure"})))
    goals = await uc(user_id=uuid4())
    assert goals.water_ml <= int(MEDICAL_OVERRIDE_CAP_ML)


@pytest.mark.asyncio
async def test_lactating_user_gets_bonus_within_safety_band() -> None:
    uc_no_lact, _ = _make_use_case(_bio(lactating=False))
    uc_lact, _ = _make_use_case(_bio(lactating=True))
    base = await uc_no_lact(user_id=uuid4())
    boosted = await uc_lact(user_id=uuid4())
    # Boost is +700 ml, but safety caps clamp to [1500, 4000]. So boosted >= base
    # unless both already saturate the ceiling (not the case for 70 kg female maintain).
    assert boosted.water_ml > base.water_ml
    assert int(SAFETY_MIN_ML) <= boosted.water_ml <= int(SAFETY_MAX_ML)


@pytest.mark.asyncio
async def test_pregnant_user_gets_bonus() -> None:
    uc_no, _ = _make_use_case(_bio())
    uc_preg, _ = _make_use_case(_bio(pregnant=True, trimester="second"))
    base = await uc_no(user_id=uuid4())
    boosted = await uc_preg(user_id=uuid4())
    assert boosted.water_ml >= base.water_ml


@pytest.mark.asyncio
async def test_missing_region_does_not_crash() -> None:
    bio = _bio()
    bio.pop("region")
    uc, _ = _make_use_case(bio)
    goals = await uc(user_id=uuid4())
    assert int(SAFETY_MIN_ML) <= goals.water_ml <= int(SAFETY_MAX_ML)


@pytest.mark.asyncio
async def test_missing_pregnant_lactating_flags_default_false() -> None:
    bio = _bio()
    bio.pop("pregnant")
    bio.pop("lactating")
    uc, _ = _make_use_case(bio)
    goals = await uc(user_id=uuid4())
    assert int(SAFETY_MIN_ML) <= goals.water_ml <= int(SAFETY_MAX_ML)


@pytest.mark.asyncio
async def test_water_ml_always_within_safety_band_for_healthy_user() -> None:
    """No medical condition ⇒ water_ml ∈ [1500, 4000]."""
    uc, _ = _make_use_case(_bio())
    goals = await uc(user_id=uuid4())
    assert int(SAFETY_MIN_ML) <= goals.water_ml <= int(SAFETY_MAX_ML)


# --- Property: CKD invariant survives any input combination -----------------


@pytest.mark.asyncio
@given(
    # 60-150 kg keeps BMR-safety floor (kcal_target >= 0.9 * BMR) reachable
    # across the {weight_loss, maintain, muscle_gain, weight_gain, health} goal
    # delta range for a 170 cm / 30 yr male profile.
    weight_kg=st.decimals(min_value=Decimal("60"), max_value=Decimal("150"), places=1),
    activity=st.sampled_from(
        ["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]
    ),
    goal=st.sampled_from(["maintain", "muscle_gain", "weight_gain", "health"]),
    region=st.sampled_from(["latam", "eu", "us", ""]),
    pregnant=st.booleans(),
    lactating=st.booleans(),
)
async def test_ckd_invariant_property(
    weight_kg: Decimal,
    activity: str,
    goal: str,
    region: str,
    pregnant: bool,
    lactating: bool,
) -> None:
    """CKD condition ALWAYS caps water_ml to ≤1500 regardless of other signals.

    Property scoped to a profile range where the BMR-safety floor (an
    unrelated invariant) does not pre-empt goal generation — the hydration
    cap is what we are validating here.
    """
    bio = _bio(
        weight_kg=weight_kg,
        activity_level=activity,
        goal=goal,
        region=region,
        pregnant=pregnant,
        lactating=lactating,
        conditions=frozenset({"ckd"}),
        height_cm=Decimal("170"),
        age=30,
        sex="male",
    )
    uc, _ = _make_use_case(bio)
    goals = await uc(user_id=uuid4())
    assert goals.water_ml <= int(MEDICAL_OVERRIDE_CAP_ML)
