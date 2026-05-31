"""ADR-0002 — dynamic metabolic recalibration.

Inputs: 14-day windowed weight series + intake series + current TDEE + biometrics.
Outputs: new TDEE (clamped ±15%) or None (skip), reason code.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.nutrition.domain.mifflin_st_jeor import compute_bmr

KCAL_PER_KG = 7700.0
MIN_DAYS = 14
MIN_WEIGHT_POINTS = 7
COOLDOWN_DAYS = 14
DELTA_RATIO_THRESHOLD = 0.5
CLAMP_PCT = 0.15

Reason = Literal["plateau", "weight_change", "goal_change", "manual"]


@dataclass(frozen=True, slots=True)
class RecalibrationInput:
    sex: str
    weight_kg_now: Decimal
    height_cm: Decimal
    age: int
    activity_factor: Decimal
    goal: str
    tdee_current: int
    days_since_last_recalibration: int
    weights: list[tuple[int, float]]  # (day_index, weight_kg) — last 14d
    kcal_in: list[int]                # daily intake — last 14d (len <= 14)


@dataclass(frozen=True, slots=True)
class RecalibrationResult:
    tdee_new: int
    bmr_new: int
    reason: Reason
    slope_kg_per_day: float
    delta_ratio: float


@dataclass(frozen=True, slots=True)
class RecalibrationSkipped:
    reason: str  # 'insufficient_data' | 'cooldown' | 'delta_below_threshold' | 'athlete_bulk'


def _winsorise(values: list[float], p_low: float = 0.05, p_high: float = 0.95) -> list[float]:
    if not values:
        return values
    sorted_v = sorted(values)
    n = len(sorted_v)
    lo = sorted_v[max(0, int(n * p_low))]
    hi = sorted_v[min(n - 1, int(n * p_high))]
    return [max(lo, min(hi, v)) for v in values]


def _ols_slope(points: list[tuple[int, float]]) -> float:
    """Slope of y vs x via OLS (closed form). Returns 0 if degenerate."""
    if len(points) < 2:
        return 0.0
    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def recalibrate(inp: RecalibrationInput) -> RecalibrationResult | RecalibrationSkipped:
    if len(inp.weights) < MIN_WEIGHT_POINTS or len(inp.kcal_in) < MIN_DAYS // 2:
        return RecalibrationSkipped("insufficient_data")
    if inp.days_since_last_recalibration < COOLDOWN_DAYS:
        return RecalibrationSkipped("cooldown")

    weights_only = [w for _, w in inp.weights]
    winsorised = _winsorise(weights_only)
    series = list(zip([d for d, _ in inp.weights], winsorised, strict=True))
    slope = _ols_slope(series)

    mean_kcal_in = statistics.fmean(inp.kcal_in)
    observed_tdee = mean_kcal_in - slope * KCAL_PER_KG

    mifflin_recalc = compute_bmr(
        sex=inp.sex, weight_kg=inp.weight_kg_now,  # type: ignore[arg-type]
        height_cm=inp.height_cm, age=inp.age,
    ) * float(inp.activity_factor)

    blended = 0.5 * mifflin_recalc + 0.5 * observed_tdee
    tdee_new = int(round(max(
        inp.tdee_current * (1 - CLAMP_PCT),
        min(inp.tdee_current * (1 + CLAMP_PCT), blended),
    )))

    expected_kg_per_day = (mean_kcal_in - inp.tdee_current) / KCAL_PER_KG
    if abs(expected_kg_per_day) < 1e-4:
        # No expected change → can't compute meaningful ratio
        return RecalibrationSkipped("delta_below_threshold")
    delta_ratio = slope / expected_kg_per_day

    # Trigger: only blend if observed reality diverges from expectation by >50%.
    if abs(delta_ratio - 1.0) <= DELTA_RATIO_THRESHOLD:
        return RecalibrationSkipped("delta_below_threshold")

    # Athlete bulk guard.
    if inp.goal == "muscle_gain" and 0.7 <= delta_ratio <= 1.5:
        return RecalibrationSkipped("athlete_bulk")

    reason: Reason = "plateau" if abs(slope) < 1e-4 else "weight_change"
    bmr_new = compute_bmr(
        sex=inp.sex, weight_kg=inp.weight_kg_now,  # type: ignore[arg-type]
        height_cm=inp.height_cm, age=inp.age,
    )
    return RecalibrationResult(
        tdee_new=tdee_new, bmr_new=bmr_new, reason=reason,
        slope_kg_per_day=slope, delta_ratio=delta_ratio,
    )
