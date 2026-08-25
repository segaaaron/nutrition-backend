"""Plan aggregate (Plan → PlanDay → PlanMeal). Framework-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from app.plan.domain.value_objects import MealTime, PlanStatus, PlanType
from app.plan.domain.water_view import WaterView


@dataclass(slots=True)
class PlanMeal:
    id: UUID
    plan_day_id: UUID
    meal_time: MealTime
    recipe_id: UUID | None
    kcal: int | None
    protein_g: int | None
    carbs_g: int | None
    fat_g: int | None
    water_ml: int | None = None
    water_pct: float | None = None
    scaled_factor: float | None = None
    # User-chosen multiplier (BE-11). Default 1.0 = no adjustment.
    user_factor: float = 1.0
    completed: bool = False
    swapped_from: UUID | None = None


@dataclass(slots=True)
class PlanDay:
    id: UUID
    plan_id: UUID
    day_index: int
    date: date
    completed: bool = False
    meals: list[PlanMeal] = field(default_factory=list)
    kcal_actual: int | None = None
    within_band: bool | None = None
    # Computed at plan generation, not persisted to DB.
    # protein_actual: daily protein sum (g) — used for ≥90% target check.
    # fiber_daily: sum of scaled fiber_g across meals (OMS target ≥25 g/day).
    # sodium_daily: sum of scaled sodium_mg across meals (OMS target <2000 mg/day).
    protein_actual: int | None = None
    fiber_daily: int | None = None
    sodium_daily: int | None = None


@dataclass(slots=True)
class Plan:
    id: UUID
    user_id: UUID
    type: PlanType
    total_days: int
    current_day: int
    status: PlanStatus
    goal: str | None
    meals_per_day: int
    preferences: list[str]
    kcal_target: int | None
    version: int
    created_at: datetime
    days: list[PlanDay] = field(default_factory=list)
    # Daily hydration view — computed from `nutritional_goals.water_ml`
    # (single source of truth). Non-persisted: assembled at create/read time.
    water_view: WaterView | None = None
    # Per-slot kcal/protein targets (migration 0020).
    # {"breakfast": {"kcal": 475, "protein_g": 33}, ...}
    slot_targets: dict | None = None
    # User locale at plan-creation time (migration 0023). Used to reconstruct
    # water_view on read. Defaults to "es" for pre-migration plans.
    locale: str = "es"

    def find_meal(self, meal_id: UUID) -> PlanMeal | None:
        for d in self.days:
            for m in d.meals:
                if m.id == meal_id:
                    return m
        return None
