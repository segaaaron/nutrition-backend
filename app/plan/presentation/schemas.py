"""Pydantic schemas for plan endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.profile.presentation.schemas import OnboardingRequest, ProfileResponse


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


PlanType = Literal["day", "week", "month"]
PlanStatus = Literal["active", "completed", "cancelled"]
MealTime = Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"]

# Preference tag: max 64 chars each, max 20 tags per request.
_PrefItem = Annotated[str, Field(min_length=1, max_length=64)]


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
    preferences: list[_PrefItem] = Field(default_factory=list, max_length=20)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
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


class PlanMealIngredient(_Strict):
    """One recipe component (ingredient) embedded in a plan meal.

    ``amount_g`` is the recipe's *native* gram amount. iOS MUST multiply it
    by the meal's ``scaled_factor`` to show the portion actually served.
    """

    name: str | None
    # BE-9: localized ingredient name. Fallback chain: EN translation (when the
    # request locale is English and a translation exists) → free_text_name
    # (mostly ES). `name` keeps the raw free_text_name for backward compat.
    name_localized: str | None = None
    amount_g: Decimal | None
    position: int
    # Human-readable quantity + prep description (e.g. "¾ taza de quinoa cocida",
    # "1 pechuga mediana"). When present, iOS shows this instead of amount_g.
    # NULL → iOS falls back to "{amount_g}g". Populated via modifier field in
    # recipe_components. Backward-compatible: existing clients ignore new fields.
    modifier: str | None = None


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
    # Full recipe detail embedded so iOS needs no extra GET /recipes/{id}.
    # Micros mirror the recipe's native (unscaled) values.
    fiber_g: int | None = None
    sugar_g: int | None = None
    sodium_mg: int | None = None
    sat_fat_g: int | None = None
    tags: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    ingredients: list[PlanMealIngredient] = Field(default_factory=list)
    completed: bool
    swapped_from: UUID | None
    # Sprint A1 — short fact-based "why this recipe" line (localized). Display only.
    rationale_localized: str | None = None


class PlanDayResponse(_Strict):
    id: UUID
    day_index: int
    date: date
    completed: bool
    breakfast: PlanMealResponse | None = None
    morning_snack: PlanMealResponse | None = None
    lunch: PlanMealResponse | None = None
    afternoon_snack: PlanMealResponse | None = None
    dinner: PlanMealResponse | None = None
    snack: PlanMealResponse | None = None
    # Actual kcal delivered after portion scaling. ±20% of daily target = within_band.
    kcal_actual: int | None = None
    within_band: bool | None = None
    # Daily protein and fiber totals — computed from scaled meal values.
    protein_actual: int | None = None
    fiber_daily: int | None = None


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


class WeightProjectionResponse(_Strict):
    """Expected weekly weight change (kg) with a ±25% confidence band."""

    weekly_kg: float
    ci_low_kg: float
    ci_high_kg: float


# E4 — retention context appended to GET /plans/active (lazy eval, no cron).
class RetentionNudge(_Strict):
    """H3 — contextual banner for streak-at-risk / comeback / milestone."""

    type: Literal["streak_at_risk", "comeback", "week1_strong", "two_weeks_milestone"]
    streak_days: int | None = None
    days_away: int | None = None
    message_es: str
    message_en: str


class WeekRecap(_Strict):
    """H4 — weekly logging summary shown on Sundays or day-N multiples of 7."""

    days_logged: int
    days_total: int
    message_es: str
    message_en: str


class TodaySummary(_Strict):
    """H5 — today's kcal progress exposed in the plan response."""

    kcal_logged: int
    kcal_target: int
    kcal_remaining: int
    pct_complete: int  # 0-100


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
    # True only on the user's very first completed plan (free tier). iOS shows paywall modal.
    paywall_signal: bool = False
    # Sprint A2 — expected weekly weight change from energy balance (kg/week,
    # negative = loss) with a ±25% honesty band. None when TDEE is unavailable.
    expected_weekly_change: WeightProjectionResponse | None = None
    # E4 — retention hooks (H3/H4/H5). All optional; omitted when not applicable.
    retention_nudge: RetentionNudge | None = None
    week_recap: WeekRecap | None = None
    today_summary: TodaySummary | None = None


class AdvanceRequest(_Strict):
    event: Literal["MEAL_COMPLETE", "DAY_COMPLETE", "SWAP_MEAL", "REGENERATE", "CANCEL"]


class SwapMealRequest(_Strict):
    reason_code: str = Field(min_length=1, max_length=64)


class SwapMealResponse(_Strict):
    alternatives: list[UUID]
