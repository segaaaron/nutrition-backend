"""Shared value objects. Frozen dataclasses for immutability + hashability."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from app.shared.domain.macro_tolerance import MACRO_TOLERANCE

Locale = Literal["en", "es"]
Region = Literal["us", "ca", "latam"]
Sex = Literal["male", "female"]


@dataclass(frozen=True, slots=True)
class Calories:
    value: int

    def __post_init__(self) -> None:
        if not 500 <= self.value <= 8000:
            raise ValueError(f"Calories out of [500..8000]: {self.value}")


@dataclass(frozen=True, slots=True)
class MacroBreakdown:
    protein_g: int
    carbs_g: int
    fat_g: int

    def derived_kcal(self) -> int:
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9

    def validate_tolerance(self, declared_kcal: int) -> bool:
        """True iff `|declared - derived| / declared <= MACRO_TOLERANCE`."""
        if declared_kcal <= 0:
            return False
        return abs(declared_kcal - self.derived_kcal()) / declared_kcal <= MACRO_TOLERANCE


@dataclass(frozen=True, slots=True)
class Kg:
    value: Decimal

    def __post_init__(self) -> None:
        if not Decimal("20") <= self.value <= Decimal("300"):
            raise ValueError(f"Kg out of [20..300]: {self.value}")


@dataclass(frozen=True, slots=True)
class Cm:
    value: Decimal

    def __post_init__(self) -> None:
        if not Decimal("50") <= self.value <= Decimal("250"):
            raise ValueError(f"Cm out of [50..250]: {self.value}")


KCAL_RANGE_WIDTH: Final[int] = 200


@dataclass(frozen=True, slots=True)
class KcalRange:
    """UI surface for daily kcal target. Width is always 200 (spec §6)."""

    min: int
    max: int

    def __post_init__(self) -> None:
        if self.max - self.min != KCAL_RANGE_WIDTH:
            raise ValueError(
                f"KcalRange width must be {KCAL_RANGE_WIDTH}, got {self.max - self.min}"
            )
        if self.min <= 0:
            raise ValueError("KcalRange.min must be positive")


_ALLOWED_FACTORS: Final[frozenset[Decimal]] = frozenset(
    {Decimal("1.20"), Decimal("1.375"), Decimal("1.55"), Decimal("1.725"), Decimal("1.90")}
)


@dataclass(frozen=True, slots=True)
class ActivityFactor:
    value: Decimal

    def __post_init__(self) -> None:
        if self.value not in _ALLOWED_FACTORS:
            raise ValueError(f"ActivityFactor must be one of {_ALLOWED_FACTORS}, got {self.value}")
