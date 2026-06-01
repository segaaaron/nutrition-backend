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


class DetectedItemDto(BaseModel):
    name: str
    estimated_amount_g: Decimal
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    confidence: float
    matched_food_id: UUID | None = None
    match_method: str | None = None


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    items: list[DetectedItemDto] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class EditDetectedItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_name: str
    corrected_food_id: UUID | None = None
    corrected_amount_g: Decimal | None = None
