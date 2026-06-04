"""Mifflin-St Jeor BMR — canonical source.

  Men:    BMR = 10*W + 6.25*H - 5*A + 5
  Women:  BMR = 10*W + 6.25*H - 5*A - 161

Source: Mifflin MD, St Jeor ST, Hill LA, Scott BJ, Daugherty SA, Koh YO.
A new predictive equation for resting energy expenditure in healthy
individuals. Am J Clin Nutr 1990;51(2):241-247.

Decimal-first per CLAUDE.md (float forbidden in nutrition math). The
literature reports ±10% individual variability around the regression;
recalibration (ADR-0002) closes the loop with observed data.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

Sex = Literal["male", "female"]

_INT: Final[Decimal] = Decimal("1")


def mifflin_st_jeor(
    *,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
    sex: Sex,
) -> Decimal:
    """Canonical Decimal BMR. kcal/day, rounded half-even."""
    base = Decimal("10") * weight_kg + Decimal("6.25") * height_cm - Decimal("5") * Decimal(age)
    offset = Decimal("5") if sex == "male" else Decimal("-161")
    return (base + offset).quantize(_INT, rounding=ROUND_HALF_EVEN)


def compute_bmr(
    *,
    sex: Sex,
    weight_kg: Decimal | float,
    height_cm: Decimal | float,
    age: int,
) -> int:
    """Backward-compat int wrapper. Delegates to canonical Decimal impl."""
    w = weight_kg if isinstance(weight_kg, Decimal) else Decimal(str(weight_kg))
    h = height_cm if isinstance(height_cm, Decimal) else Decimal(str(height_cm))
    return int(mifflin_st_jeor(weight_kg=w, height_cm=h, age=age, sex=sex))
