"""FoodLog entity + DailyTotals VO + FoodLogSearchQuery VO.

The food_logs table is already provisioned by migration 0001. This module adds
the domain-layer view used by Sprint 7 query/aggregate use cases. Stays
framework-agnostic — repositories materialise rows into these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

MealTime = Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"]
LogMethod = Literal["photo", "voice", "text", "barcode", "search", "manual"]


@dataclass(slots=True)
class FoodLog:
    """Aggregate root for a single eaten item.

    Invariant: kcal/macros are non-negative integers (rounded ints stored in
    DB). Confidence in [0,1] when present.
    """

    id: UUID
    user_id: UUID
    date: date
    meal_time: MealTime
    method: LogMethod
    food_id: UUID | None = None
    recipe_id: UUID | None = None
    free_text_name: str | None = None
    amount_g: Decimal | None = None
    kcal: int | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None
    confidence: Decimal | None = None
    source_image_url: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DailyTotals:
    """Aggregated macro/micro totals for one user-day.

    Macros use int (gram rounding is acceptable for UI). Micros use float
    because RDA targets routinely span 5+ orders of magnitude (mcg → g).
    """

    date: date
    kcal: int = 0
    protein_g: int = 0
    carbs_g: int = 0
    fat_g: int = 0
    fiber_g: int = 0
    sugar_g: int = 0
    sodium_mg: int = 0
    micros: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "kcal": self.kcal,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "fiber_g": self.fiber_g,
            "sugar_g": self.sugar_g,
            "sodium_mg": self.sodium_mg,
            "micros": self.micros,
        }


@dataclass(frozen=True, slots=True)
class FoodLogSearchQuery:
    user_id: UUID
    date_from: date | None = None
    date_to: date | None = None
    meal_time: MealTime | None = None
    method: LogMethod | None = None
    cursor: str | None = None  # opaque (created_at,id)
    limit: int = 50
