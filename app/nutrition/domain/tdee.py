"""TDEE = BMR * activity_factor."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal


def compute_tdee(bmr: int, activity_factor: Decimal | float) -> int:
    # Decimal throughout for consistency with mifflin_st_jeor (the
    # float path used Python's round(), mixing rounding semantics).
    af = activity_factor if isinstance(activity_factor, Decimal) else Decimal(str(activity_factor))
    return int((Decimal(bmr) * af).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
