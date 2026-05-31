"""TDEE = BMR * activity_factor."""
from __future__ import annotations

from decimal import Decimal


def compute_tdee(bmr: int, activity_factor: Decimal | float) -> int:
    return int(round(bmr * float(activity_factor)))
