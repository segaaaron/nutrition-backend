"""Plan domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class PlanCreated(DomainEvent):
    plan_id: UUID
    user_id: UUID
    type: str
    total_days: int
    at: datetime


@dataclass(frozen=True, slots=True)
class MealCompleted(DomainEvent):
    plan_id: UUID
    user_id: UUID
    meal_id: UUID
    at: datetime
    meal_time: str | None = None
    recipe_id: UUID | None = None
    kcal: int | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None


@dataclass(frozen=True, slots=True)
class DayCompleted(DomainEvent):
    plan_id: UUID
    user_id: UUID
    day_index: int
    at: datetime


@dataclass(frozen=True, slots=True)
class PlanCompleted(DomainEvent):
    plan_id: UUID
    user_id: UUID
    at: datetime


@dataclass(frozen=True, slots=True)
class MealSwapped(DomainEvent):
    plan_id: UUID
    meal_id: UUID
    from_recipe_id: UUID
    to_recipe_id: UUID
    reason_code: str
    at: datetime


@dataclass(frozen=True, slots=True)
class PlanRegenerated(DomainEvent):
    plan_id: UUID
    user_id: UUID
    at: datetime
