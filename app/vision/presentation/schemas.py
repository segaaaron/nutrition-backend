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
    protein_g: int
    carbs_g: int
    fat_g: int
    confidence: float
    food_group: FoodGroupDto | None = None
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
    summary: str | None = None
    error_code: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class EditDetectedItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_name: str
    corrected_food_id: UUID | None = None
    corrected_amount_g: Decimal | None = None
