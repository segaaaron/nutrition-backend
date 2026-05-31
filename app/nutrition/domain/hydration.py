"""Water target.

Heuristic — 35 ml/kg bodyweight (NHANES baseline) + 350 ml per activity factor
step above sedentary. Clamped to [1500, 5000] ml.
"""
from __future__ import annotations

from decimal import Decimal

_FACTOR_STEPS = {1.20: 0, 1.375: 1, 1.55: 2, 1.725: 3, 1.90: 4}


def compute_water_ml(*, weight_kg: Decimal | float, activity_factor: Decimal | float) -> int:
    w = float(weight_kg)
    af = round(float(activity_factor), 3)
    step = _FACTOR_STEPS.get(af, 0)
    base = int(round(35 * w))
    bonus = step * 350
    return max(1500, min(5000, base + bonus))
