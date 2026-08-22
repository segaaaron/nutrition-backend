"""Nutritional-goals API schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
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
    kcal_today: int          # kcal logged today (resets at midnight)
    kcal_delta_today: int    # kcal_today − kcal_target; negative = deficit (good for loss)


class WeightProgressResponse(_Strict):
    """Read-only weight trend — answers "Am I losing weight as planned?"."""

    slope_kg_per_week: float | None     # None when insufficient data
    trend_label: str                     # "losing" | "gaining" | "plateau" | "insufficient_data"
    weight_points: int                   # weigh-in entries used for trend
    days_tracked_last_14: int
    projected_goal_date: date | None     # based on current slope; None when no target or insufficient
    vs_plan: str                         # "on_track" | "ahead" | "behind" | "maintain" | "insufficient_data"


class WeightInsightsOut(_Strict):
    """Weight insights derived on-the-fly from biometrics.

    Embedded inside GoalsResponse. All numeric fields serialise as JSON numbers.
    """

    bmi: float
    bmi_category: str           # "underweight" | "healthy" | "overweight" | "obese"
    bmi_label_es: str           # Human-readable Spanish label for iOS display

    ideal_weight_min_kg: float
    ideal_weight_max_kg: float
    peterson_ideal_kg: float    # Peterson 2016 point estimate — most accurate
    devine_reference_kg: float | None  # None when height < 152.4 cm

    weight_to_lose_kg: float | None    # None when already in healthy range or pregnant
    weight_gap_direction: str   # "lose" | "gain" | "maintain"
    weekly_rate_kg: float
    weekly_rate_label: str      # "slow" | "moderate" | "fast"
    estimated_weeks: int | None
    estimated_date: date | None

    latam_context_note: bool    # True for BMI 25–27.9 (LATAM risk zone — Sci Reports 2024)


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
    # Dietary targets for app progress bars.
    # fiber: 14 g / 1,000 kcal (Dietary Guidelines 2020-2025).
    # sodium: 2,000 mg/day general population (WHO 2023).
    fiber_target_g: int = 0
    sodium_target_mg: int = 2000
    weight_insights: WeightInsightsOut | None = None  # None when biometrics unavailable
