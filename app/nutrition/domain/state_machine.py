"""NutritionalGoals state machine.

Invariant: exactly one row per user with valid_to IS NULL (current). Enforced
by the DB partial unique index `one_current_goals` and by `expire_and_activate`
which is the only state-changing operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

Reason = Literal["onboarding", "weight_change", "goal_change", "plateau", "manual"]


@dataclass(slots=True)
class NutritionalGoals:
    id: UUID
    user_id: UUID
    kcal_min: int
    kcal_max: int
    protein_g: int
    carbs_g: int
    fat_g: int
    water_ml: int
    bmr: int
    tdee: int
    activity_factor: Decimal
    reason: Reason
    valid_from: datetime
    valid_to: datetime | None = None
    # Dietary targets surfaced to the app for progress bars.
    # fiber: 14 g / 1,000 kcal (Dietary Guidelines 2020-2025).
    # sodium: 2,000 mg/day general population (WHO 2023).
    fiber_target_g: int = 0
    sodium_target_mg: int = 2000

    @classmethod
    def new(
        cls,
        *,
        user_id: UUID,
        kcal_min: int,
        kcal_max: int,
        protein_g: int,
        carbs_g: int,
        fat_g: int,
        water_ml: int,
        bmr: int,
        tdee: int,
        activity_factor: Decimal,
        reason: Reason,
        valid_from: datetime,
        fiber_target_g: int = 0,
        sodium_target_mg: int = 2000,
    ) -> NutritionalGoals:
        if kcal_max - kcal_min != 200:
            raise ValueError("kcal_max - kcal_min must equal 200")
        return cls(
            id=uuid4(),
            user_id=user_id,
            kcal_min=kcal_min,
            kcal_max=kcal_max,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            water_ml=water_ml,
            bmr=bmr,
            tdee=tdee,
            activity_factor=activity_factor,
            reason=reason,
            valid_from=valid_from,
            valid_to=None,
            fiber_target_g=fiber_target_g,
            sodium_target_mg=sodium_target_mg,
        )
