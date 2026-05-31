"""Nutritional-goals API schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoalsResponse(_Strict):
    id: UUID
    kcal_min: int
    kcal_max: int
    protein_g: int
    carbs_g: int
    fat_g: int
    water_ml: int
    bmr: int
    tdee: int
    activity_factor: Decimal
    reason: str
    valid_from: datetime
    valid_to: datetime | None
