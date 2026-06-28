"""Pydantic schemas for plan endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.profile.presentation.schemas import OnboardingRequest, ProfileResponse


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


PlanType = Literal["day", "week", "month"]
PlanStatus = Literal["active", "completed", "cancelled"]
MealTime = Literal["breakfast", "lunch", "dinner", "snack"]


class PlanJobRef(BaseModel):
    """Async Arq job handle returned by `POST /plans`."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["queued", "generating", "ready"]


class CreatePlanRequest(_Strict):
    """Unified plan-generation request.

    Two iOS use-cases share this single endpoint:

    1. **Onboarding final step** — client sends ``profile`` populated with the
       full :class:`OnboardingRequest` payload. The handler upserts
       ``user_profiles`` + computes ``nutritional_goals`` atomically, then
       enqueues plan generation.
    2. **Regeneration from inside the app** — client sends ``{}`` (or just
       ``type``/``preferences``/``seed``). The handler reads the existing
       profile + goals and enqueues plan generation. Missing profile → 422.

    All plan-shaping fields (``type``/``preferences``/``seed``) are optional;
    ``type`` defaults to ``"week"`` to keep the iOS happy-path single-line.
    """

    type: PlanType = "week"
    preferences: list[str] = Field(default_factory=list)
    seed: int | None = None
    profile: OnboardingRequest | None = None


class CreatePlanResponse(_Strict):
    job_id: str
    plan_id: UUID | None = None
    status: Literal["queued", "generating", "ready"]
    # Populated only when ``profile`` was sent in the request (atomic
    # onboarding + plan flow). Echo lets iOS skip a second `GET /me`.
    profile: ProfileResponse | None = None
    # Async job handle, mirrors the top-level fields. Kept as a nested
    # object for the new iOS flow; the legacy flat fields above stay for
    # backward compatibility with existing clients/tests.
    plan_job: PlanJobRef | None = None


class PlanMealResponse(_Strict):
    id: UUID
    meal_time: MealTime
    recipe_id: UUID | None
    name_localized: str | None = None
    description_localized: str | None = None
    kcal: int | None
    protein_g: int | None
    carbs_g: int | None
    fat_g: int | None
    # Portion-scaling multiplier vs the recipe's native macros. iOS MUST
    # multiply displayed ingredient amounts by this value. NULL = legacy → 1.0.
    scaled_factor: float | None = None
    image_url: str | None = None
    prep_min: int | None = None
    instructions_localized: list[str] = Field(default_factory=list)
    completed: bool
    swapped_from: UUID | None


class PlanDayResponse(_Strict):
    id: UUID
    day_index: int
    date: date
    completed: bool
    meals: list[PlanMealResponse]
    # Actual kcal delivered after portion scaling. ±20% of daily target = within_band.
    kcal_actual: int | None = None
    within_band: bool | None = None


class WaterSlotResponse(_Strict):
    time: str
    ml: int
    label: str


class WaterTargetResponse(_Strict):
    """Daily hydration view (8 chronological slots + coach message).

    ``total_ml`` mirrors the persisted ``nutritional_goals.water_ml`` —
    schedule ml values sum to ``total_ml`` exactly.
    """

    total_ml: int
    glass_ml: int
    n_glasses: int
    schedule: list[WaterSlotResponse]
    message: str


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
    water_target: WaterTargetResponse | None = None
    # Per-slot kcal/protein targets so iOS can show the distribution breakdown.
    # {"breakfast": {"kcal": 475, "protein_g": 33}, "lunch": {...}, ...}
    slot_targets: dict | None = None


class AdvanceRequest(_Strict):
    event: Literal["MEAL_COMPLETE", "DAY_COMPLETE", "SWAP_MEAL", "REGENERATE", "CANCEL"]


class SwapMealRequest(_Strict):
    reason_code: str = Field(min_length=1, max_length=64)


class SwapMealResponse(_Strict):
    alternatives: list[UUID]
