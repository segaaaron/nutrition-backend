"""Mifflin-St Jeor BMR.

  Men:    BMR = 10*W + 6.25*H - 5*A + 5
  Women:  BMR = 10*W + 6.25*H - 5*A - 161

Returns BMR in kcal/day as an int (rounded). The clinical literature reports
±10% individual variability around the regression; we round at the surface and
let recalibration (ADR-0002) close the loop with observed data.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

Sex = Literal["male", "female"]


def compute_bmr(*, sex: Sex, weight_kg: Decimal | float, height_cm: Decimal | float, age: int) -> int:
    w = float(weight_kg)
    h = float(height_cm)
    base = 10.0 * w + 6.25 * h - 5.0 * age
    if sex == "male":
        bmr = base + 5.0
    elif sex == "female":
        bmr = base - 161.0
    else:
        raise ValueError(f"unknown sex: {sex!r}")
    return int(round(bmr))
