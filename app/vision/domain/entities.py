"""Vision domain entities.

`VisionJob` is the aggregate root for one photo→kcal/macros pipeline run.
`DetectedFoodItem` is the upstream LLM-emitted item with provenance.
`VisionResult` is the validated, food-matched output persisted to food_logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

VisionJobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


@dataclass(slots=True)
class DetectedFoodItem:
    name: str
    estimated_amount_g: Decimal
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    confidence: float
    matched_food_id: UUID | None = None
    matched_name_norm: str | None = None
    match_method: str | None = None  # 'trigram' | 'embedding' | 'unmatched'


@dataclass(slots=True)
class VisionResult:
    items: list[DetectedFoodItem]
    total_kcal: int
    total_protein_g: int
    total_carbs_g: int
    total_fat_g: int


@dataclass(slots=True)
class VisionJob:
    id: UUID = field(default_factory=uuid4)
    user_id: UUID | None = None
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    status: VisionJobStatus = "queued"
    image_sha256: str = ""
    image_bytes: int = 0
    idempotency_key: str | None = None
    prompt_sha256: str | None = None
    detected_items: list[DetectedFoodItem] = field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
