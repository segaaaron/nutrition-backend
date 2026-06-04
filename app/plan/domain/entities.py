"""Plan aggregate (Plan → PlanDay → PlanMeal). Framework-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from app.plan.domain.value_objects import MealTime, PlanStatus, PlanType


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

    def find_meal(self, meal_id: UUID) -> PlanMeal | None:
        for d in self.days:
            for m in d.meals:
                if m.id == meal_id:
                    return m
        return None
