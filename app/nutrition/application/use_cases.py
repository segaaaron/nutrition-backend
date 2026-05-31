"""Nutrition use cases.

Two flows:
  1) compute_initial_goals — invoked on onboarding (or first valid biometrics)
  2) recalibrate_goals — event handler for WeightLogged (subscribed in event bus)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.event_bus import EventBus
from app.nutrition.domain.hydration import compute_water_ml
from app.nutrition.domain.kcal_range import to_range
from app.nutrition.domain.macro_partitioning import compute_macros
from app.nutrition.domain.mifflin_st_jeor import compute_bmr
from app.nutrition.domain.recalibration import (
    RecalibrationInput,
    RecalibrationResult,
    RecalibrationSkipped,
    recalibrate,
)
from app.nutrition.domain.state_machine import NutritionalGoals
from app.nutrition.domain.tdee import compute_tdee


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


_GOAL_KCAL_DELTA = {
    "weight_loss": -500,
    "maintain":    0,
    "muscle_gain": +300,
    "weight_gain": +500,
    "health":      0,
}

_ACTIVITY_FACTOR = {
    "sedentary":          Decimal("1.20"),
    "lightly_active":     Decimal("1.375"),
    "moderately_active":  Decimal("1.55"),
    "very_active":        Decimal("1.725"),
    "extra_active":       Decimal("1.90"),
}


class NutritionalGoalsRepository(Protocol):
    async def get_current(self, user_id: UUID) -> NutritionalGoals | None: ...
    async def list_history(self, user_id: UUID, limit: int) -> list[NutritionalGoals]: ...
    async def expire_current_and_insert(
        self, user_id: UUID, new_goals: NutritionalGoals,
    ) -> NutritionalGoals: ...


class ProfileReader(Protocol):
    async def biometrics(self, user_id: UUID) -> dict | None: ...
    """Returns {weight_kg, height_cm, age, sex, goal, activity_level} or None."""


class TrackingReader(Protocol):
    async def weight_series_14d(self, user_id: UUID) -> list[tuple[int, float]]: ...
    async def kcal_in_14d(self, user_id: UUID) -> list[int]: ...


def _build_goals(
    *,
    user_id: UUID,
    sex: str,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
    goal: str,
    activity_level: str,
    reason: str,
) -> NutritionalGoals:
    af = _ACTIVITY_FACTOR[activity_level]
    bmr = compute_bmr(sex=sex, weight_kg=weight_kg, height_cm=height_cm, age=age)  # type: ignore[arg-type]
    tdee_base = compute_tdee(bmr, af)
    kcal_target = max(800, tdee_base + _GOAL_KCAL_DELTA.get(goal, 0))
    macros = compute_macros(kcal_target=kcal_target, weight_kg=weight_kg, goal=goal)  # type: ignore[arg-type]
    krange = to_range(kcal_target)
    water = compute_water_ml(weight_kg=weight_kg, activity_factor=af)
    return NutritionalGoals.new(
        user_id=user_id, kcal_min=krange.min, kcal_max=krange.max,
        protein_g=macros.protein_g, carbs_g=macros.carbs_g, fat_g=macros.fat_g,
        water_ml=water, bmr=bmr, tdee=tdee_base, activity_factor=af,
        reason=reason,  # type: ignore[arg-type]
        valid_from=_now(),
    )


@dataclass(slots=True)
class ComputeInitialGoals:
    profile_reader: ProfileReader
    goals_repo: NutritionalGoalsRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> NutritionalGoals:
        bio = await self.profile_reader.biometrics(user_id)
        if not bio:
            raise NotFoundError("profile_not_found")
        for k in ("weight_kg", "height_cm", "age", "sex", "goal", "activity_level"):
            if bio.get(k) is None:
                raise BusinessRuleViolation(f"profile_missing:{k}")
        goals = _build_goals(
            user_id=user_id, sex=bio["sex"], weight_kg=bio["weight_kg"],
            height_cm=bio["height_cm"], age=bio["age"], goal=bio["goal"],
            activity_level=bio["activity_level"], reason="onboarding",
        )
        return await self.goals_repo.expire_current_and_insert(user_id, goals)


@dataclass(slots=True)
class RecalibrateGoals:
    profile_reader: ProfileReader
    tracking_reader: TrackingReader
    goals_repo: NutritionalGoalsRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> RecalibrationResult | RecalibrationSkipped:
        bio = await self.profile_reader.biometrics(user_id)
        current = await self.goals_repo.get_current(user_id)
        if not bio or not current:
            return RecalibrationSkipped("no_baseline")
        weights = await self.tracking_reader.weight_series_14d(user_id)
        kcal_in = await self.tracking_reader.kcal_in_14d(user_id)

        # days_since_last_recalibration — proxy via current.valid_from to now.
        days_since = max(0, (_now() - current.valid_from).days)

        result = recalibrate(RecalibrationInput(
            sex=bio["sex"], weight_kg_now=bio["weight_kg"],
            height_cm=bio["height_cm"], age=bio["age"],
            activity_factor=current.activity_factor, goal=bio["goal"],
            tdee_current=current.tdee,
            days_since_last_recalibration=days_since,
            weights=weights, kcal_in=kcal_in,
        ))
        if isinstance(result, RecalibrationSkipped):
            return result

        # Rebuild full goals row using the new TDEE (rederive macros + water).
        af = current.activity_factor
        # We back into kcal_target from new TDEE + goal delta.
        kcal_target = max(800, result.tdee_new + _GOAL_KCAL_DELTA.get(bio["goal"], 0))
        macros = compute_macros(kcal_target=kcal_target, weight_kg=bio["weight_kg"], goal=bio["goal"])
        krange = to_range(kcal_target)
        water = compute_water_ml(weight_kg=bio["weight_kg"], activity_factor=af)

        new_goals = NutritionalGoals.new(
            user_id=user_id, kcal_min=krange.min, kcal_max=krange.max,
            protein_g=macros.protein_g, carbs_g=macros.carbs_g, fat_g=macros.fat_g,
            water_ml=water, bmr=result.bmr_new, tdee=result.tdee_new,
            activity_factor=af, reason=result.reason, valid_from=_now(),
        )
        await self.goals_repo.expire_current_and_insert(user_id, new_goals)
        return result


@dataclass(slots=True)
class GetCurrentGoals:
    goals_repo: NutritionalGoalsRepository

    async def __call__(self, *, user_id: UUID) -> NutritionalGoals:
        g = await self.goals_repo.get_current(user_id)
        if g is None:
            raise NotFoundError("goals_not_found")
        return g


@dataclass(slots=True)
class GetGoalsHistory:
    goals_repo: NutritionalGoalsRepository

    async def __call__(self, *, user_id: UUID, limit: int = 20) -> list[NutritionalGoals]:
        return await self.goals_repo.list_history(user_id, limit)
