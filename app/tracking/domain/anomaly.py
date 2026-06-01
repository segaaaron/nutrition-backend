"""Anomaly guards for tracking inputs (OWASP API4 — Resource Consumption).

Catches impossible / abuse / data-quality issues at write time. Distinct
from validation (which checks types) — these enforce *physiological*
plausibility ranges.

Why backend (not just client): client validation is bypassable. Bad data
in tracking poisons downstream nutrition recalibration (ADR-0002) and
plateau detection, which silently degrades plan quality for everyone.
"""
from __future__ import annotations

from decimal import Decimal

# Physiological bounds. Conservative — catches typos and abuse, NOT
# extreme-but-real cases. Edge-of-distribution users should still pass.
MIN_WEIGHT_KG = Decimal("25")    # below = data error or anorexia clinical case
MAX_WEIGHT_KG = Decimal("400")   # above = data error (heaviest verified ~440kg)
MIN_BODYFAT_PCT = Decimal("3")   # competitive bodybuilder floor
MAX_BODYFAT_PCT = Decimal("70")  # extreme obesity ceiling
MIN_WAIST_CM = Decimal("40")
MAX_WAIST_CM = Decimal("250")

MAX_DELTA_KG_PER_DAY = Decimal("10")   # any 24h change >10kg = error
MAX_DELTA_KG_PER_WEEK = Decimal("15")  # 1.5kg/d sustained = data error or medical


class WeightAnomalyError(ValueError):
    """Raised when weight reading fails physiological plausibility."""


def assert_weight_plausible(weight_kg: Decimal) -> None:
    if weight_kg < MIN_WEIGHT_KG:
        raise WeightAnomalyError(f"weight_below_min:{weight_kg}<{MIN_WEIGHT_KG}")
    if weight_kg > MAX_WEIGHT_KG:
        raise WeightAnomalyError(f"weight_above_max:{weight_kg}>{MAX_WEIGHT_KG}")


def assert_bodyfat_plausible(pct: Decimal | None) -> None:
    if pct is None:
        return
    if pct < MIN_BODYFAT_PCT:
        raise WeightAnomalyError(f"bodyfat_below_min:{pct}<{MIN_BODYFAT_PCT}")
    if pct > MAX_BODYFAT_PCT:
        raise WeightAnomalyError(f"bodyfat_above_max:{pct}>{MAX_BODYFAT_PCT}")


def assert_waist_plausible(waist_cm: Decimal | None) -> None:
    if waist_cm is None:
        return
    if waist_cm < MIN_WAIST_CM:
        raise WeightAnomalyError(f"waist_below_min:{waist_cm}")
    if waist_cm > MAX_WAIST_CM:
        raise WeightAnomalyError(f"waist_above_max:{waist_cm}")


def assert_weight_delta_plausible(
    new_weight_kg: Decimal,
    last_weight_kg: Decimal | None,
    days_since_last: int,
) -> None:
    """Reject impossible day-over-day swings. days_since_last clamped to 1
    when last reading is older than 1 day so we still catch spikes."""
    if last_weight_kg is None:
        return
    delta = abs(new_weight_kg - last_weight_kg)
    span_days = max(1, days_since_last)
    daily_rate = delta / span_days
    if daily_rate > MAX_DELTA_KG_PER_DAY:
        raise WeightAnomalyError(
            f"weight_delta_too_large:{delta}kg/{span_days}d>{MAX_DELTA_KG_PER_DAY}kg/d"
        )
