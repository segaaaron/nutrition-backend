"""Pydantic schemas for plan endpoints."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


PlanType = Literal["day", "week", "month"]
PlanStatus = Literal["active", "completed", "cancelled"]
MealTime = Literal["breakfast", "lunch", "dinner", "snack"]


class CreatePlanRequest(_Strict):
    type: PlanType
    preferences: list[str] = Field(default_factory=list)
    seed: int | None = None


class CreatePlanResponse(_Strict):
    job_id: str
    plan_id: UUID | None = None
    status: Literal["queued", "generating", "ready"]


class PlanMealResponse(_Strict):
    id: UUID
    meal_time: MealTime
    recipe_id: UUID | None
    kcal: int | None
    protein_g: int | None
    carbs_g: int | None
    fat_g: int | None
    completed: bool
    swapped_from: UUID | None


class PlanDayResponse(_Strict):
    id: UUID
    day_index: int
    date: date
    completed: bool
    meals: list[PlanMealResponse]


class PlanResponse(_Strict):
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
    days: list[PlanDayResponse]


class AdvanceRequest(_Strict):
    event: Literal["MEAL_COMPLETE", "DAY_COMPLETE", "SWAP_MEAL", "REGENERATE", "CANCEL"]


class SwapMealRequest(_Strict):
    reason_code: str = Field(min_length=1, max_length=64)


class SwapMealResponse(_Strict):
    alternatives: list[UUID]
