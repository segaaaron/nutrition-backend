"""Vision domain entities.

`VisionJob` is the aggregate root for one photo→kcal/macros pipeline run.
`DetectedFoodItem` is the upstream LLM-emitted item with provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

VisionJobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]

# Closed food-group vocabulary the vision LLM classifies each item into
# (strict enum in VISION_SCHEMA). "other" is the parser fallback for any
# out-of-vocabulary value so one bad row never drops the whole item.
FoodGroup = Literal[
    "vegetable",
    "fruit",
    "grain",
    "protein",
    "dairy",
    "fat",
    "sweet",
    "beverage",
    "other",
]


@dataclass(slots=True)
class DetectedFoodItem:
    name: str
    estimated_amount_g: Decimal
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    confidence: float
    food_group: FoodGroup | None = None
    matched_food_id: UUID | None = None
    matched_name_norm: str | None = None
    match_method: str | None = None  # 'trigram' | 'embedding' | 'unmatched'
    # Plate Decomposition 2.0 (optional — older cached JSONB rows lack them).
    role: str | None = None  # main|side|sauce|condiment|cooking_fat|garnish|sweetener|beverage_base
    prep_method: str | None = None  # deep_fried|fried|sauteed|grilled|boiled|steamed|baked|stewed|raw|unknown
    kcal_min: int | None = None
    kcal_max: int | None = None
    inferred: bool = False  # True = added by hidden-calorie post-pass, not detected by the LLM
    fiber_g: int = 0  # dietary fiber — critical for diabetes_t2 / digestive-health users
    sugar_g: int = 0  # total sugars — critical for diabetes_t2 / hypertension users
    count: int = 1  # number of identical visible units; all amounts already multiplied by this
    # BE-5: normalized bounding box (x, y, w, h) in 0..1, origin top-left, so
    # iOS can annotate the photo. None when the model can't locate the item.
    bbox: tuple[float, float, float, float] | None = None
    # True when the plate is an integrated mixed preparation (guiso, arroz con
    # pollo, fideos salteados) where ingredients are not separable visually.
    # Signals higher kcal estimation uncertainty → ±30% range instead of ±20%.
    is_mixed_dish: bool = False
    # G3: 2-4 alternative food names when the model is uncertain about identity
    # (confidence < 0.7). Empty list = no ambiguity. Client renders as tap-chips
    # so the user can correct in one tap without opening the full edit flow.
    ambiguous_options: list[str] = field(default_factory=list)
    # Plate-level dish name extracted from the LLM output and propagated to all
    # items. Used ONLY by the triangulation engine for catalog lookup — never
    # shown to users or stored in food_logs.
    plate_dish_name: str | None = None


@dataclass(slots=True)
class VisionJob:
    id: UUID = field(default_factory=uuid4)
    user_id: UUID | None = None
    meal_time: Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"] = "lunch"
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
    # B7: IDs of food_log rows created by this job (empty when persist=false)
    food_log_ids: list[UUID] = field(default_factory=list)
    # Number of people sharing the plate (1..8). Detection items represent the
    # full plate; this value divides amounts at food_log write and in the response.
    servings: int = 1
