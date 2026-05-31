"""Recipes value objects — search query DTOs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MealTime = Literal["breakfast", "lunch", "dinner", "snack"]


@dataclass(frozen=True, slots=True)
class RecipeSearchQuery:
    """Filter bag for `GET /recipes` and `POST /recipes/search/semantic`.

    Invariants:
      - At least one region is required (multi-region catalog — ADR-0008).
      - `allergens_exclude` is a hard filter (never returns positives) — ADR-0001.
      - `conditions` activates contraindication exclusion + recommendation boost.
    """

    q: str | None = None
    meal_time: MealTime | None = None
    regions: list[str] = field(default_factory=list)
    allergens_exclude: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    max_kcal: int | None = None
    min_protein_g: int | None = None
    ingredients_avoid: list[str] = field(default_factory=list)
    target_goals: list[str] = field(default_factory=list)
    limit: int = 20
    cursor_last_id: str | None = None
    cursor_last_score: float | None = None

    def __post_init__(self) -> None:
        if not (1 <= self.limit <= 100):
            raise ValueError("limit must be in [1..100]")


@dataclass(frozen=True, slots=True)
class FoodSearchQuery:
    q: str | None = None
    country: str | None = None
    verified_only: bool = False
    limit: int = 20
    cursor_last_id: str | None = None
    cursor_last_score: float | None = None

    def __post_init__(self) -> None:
        if not (1 <= self.limit <= 100):
            raise ValueError("limit must be in [1..100]")
