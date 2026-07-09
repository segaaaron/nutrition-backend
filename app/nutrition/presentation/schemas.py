"""Nutritional-goals API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeeklySummaryResponse(_Strict):
    logged_days: int
    window_days: int
    avg_kcal: int
    kcal_target: int
    avg_protein_g: int
    protein_target_g: int
    water_today_ml: int
    water_target_ml: int
    streak_days: int


class GoalsResponse(_Strict):
    id: UUID
    kcal_min: int
    kcal_max: int
    kcal_target: int  # midpoint of min/max — single value for iOS daily target display
    protein_g: int
    carbs_g: int
    fat_g: int
    water_ml: int
    bmr: int
    tdee: int
    activity_factor: float
    reason: str
    valid_from: datetime
    valid_to: datetime | None
