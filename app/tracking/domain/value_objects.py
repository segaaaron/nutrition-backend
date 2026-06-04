"""Tracking value objects — volume + body composition."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Volume:
    ml: int

    def __post_init__(self) -> None:
        if not 1 <= self.ml <= 5000:
            raise ValueError(f"Volume out of [1..5000] ml: {self.ml}")


@dataclass(frozen=True, slots=True)
class BodyComposition:
    weight_kg: Decimal
    body_fat_pct: Decimal | None = None
    waist_cm: Decimal | None = None

    def __post_init__(self) -> None:
        if not Decimal("20") <= self.weight_kg <= Decimal("300"):
            raise ValueError("weight_kg out of [20..300]")
        if self.body_fat_pct is not None and not (
            Decimal("3") <= self.body_fat_pct <= Decimal("60")
        ):
            raise ValueError("body_fat_pct out of [3..60]")
        if self.waist_cm is not None and not (Decimal("30") <= self.waist_cm <= Decimal("200")):
            raise ValueError("waist_cm out of [30..200]")
