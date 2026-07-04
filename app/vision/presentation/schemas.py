"""Pydantic DTOs for the vision presentation layer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubmitPhotoResponse(BaseModel):
    job_id: UUID
    status: Literal["queued"] = "queued"


FoodGroupDto = Literal[
    "vegetable", "fruit", "grain", "protein", "dairy", "fat", "sweet", "beverage", "other"
]


class DetectedItemDto(BaseModel):
    name: str
    estimated_amount_g: Decimal
    kcal: int
    kcal_min: int | None = None
    kcal_max: int | None = None
    protein_g: int
    carbs_g: int
    fat_g: int
    fiber_g: int = 0
    sugar_g: int = 0
    confidence: float
    food_group: FoodGroupDto | None = None
    # Plate Decomposition 2.0 fields — role/prep_method help users understand
    # WHY calorie counts differ (e.g. "fried" vs "grilled").
    role: str | None = None
    prep_method: str | None = None
    inferred: bool = False
    matched_food_id: UUID | None = None
    match_method: str | None = None


class PlateGroupDto(BaseModel):
    """One food-group bucket of the plate breakdown (e.g. all vegetables)."""

    group: FoodGroupDto
    label: str
    item_names: list[str]
    total_kcal: int


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    items: list[DetectedItemDto] = Field(default_factory=list)
    # Populated only when status == "completed": deterministic, localized
    # plate explanation built server-side from the detected items.
    groups: list[PlateGroupDto] = Field(default_factory=list)
    total_kcal: int | None = None
    # kcal_min/max: caloric range across all items (missing kcal_min/max on
    # an item falls back to its kcal point estimate so the range is always ≤
    # kcal_min and ≥ kcal_max from the item perspective).
    total_kcal_min: int | None = None
    total_kcal_max: int | None = None
    total_protein_g: int | None = None
    total_carbs_g: int | None = None
    total_fat_g: int | None = None
    total_fiber_g: int | None = None
    total_sugar_g: int | None = None
    # Percentage of the user's daily kcal goal this plate represents.
    # Null when goals are not set or plate total is unavailable.
    pct_daily_kcal: float | None = None
    summary: str | None = None
    error_code: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class EditDetectedItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_name: str
    corrected_food_id: UUID | None = None
    corrected_amount_g: Decimal | None = None
