"""Recipes domain entities — framework-agnostic.

`Recipe` is the aggregate root. `RecipeComponent` is owned by a recipe; `Food`
is its own aggregate (catalog item). Translation maps live on the aggregate
itself (jsonb in the schema); the application layer projects them per
`Accept-Language`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

MealTime = Literal["breakfast", "lunch", "dinner", "snack"]


@dataclass(slots=True)
class RecipeComponent:
    id: UUID
    recipe_id: UUID
    food_id: UUID | None
    sub_recipe_id: UUID | None
    free_text_name: str | None
    amount_g: Decimal | None
    modifier: str | None
    position: int

    def __post_init__(self) -> None:
        # Mirror the SQL CHECK in migration 0001.
        if not (self.food_id or self.sub_recipe_id or self.free_text_name):
            raise ValueError("RecipeComponent requires food_id, sub_recipe_id, or free_text_name")


@dataclass(slots=True)
class Recipe:
    id: UUID
    name_en: str
    name_translations: dict[str, str]
    description_en: str | None
    description_translations: dict[str, str]
    image_url: str | None
    kcal: int | None
    protein_g: int | None
    carbs_g: int | None
    fat_g: int | None
    fiber_g: int
    sugar_g: int
    sodium_mg: int
    sat_fat_g: int
    tags: list[str]
    meal_time: MealTime | None
    prep_min: int | None
    instructions_en: list[str]
    instructions_translations: dict[str, list[str]]
    regions: list[str]
    allergens: list[str]
    recommended_conditions: list[str]
    contraindicated_conditions: list[str]
    target_goals: list[str]
    components: list[RecipeComponent] = field(default_factory=list)
    created_at: datetime | None = None

    def translated_name(self, locale: str) -> str:
        return self.name_translations.get(locale) or self.name_en

    def translated_description(self, locale: str) -> str | None:
        return self.description_translations.get(locale) or self.description_en

    def translated_instructions(self, locale: str) -> list[str]:
        return self.instructions_translations.get(locale) or self.instructions_en


@dataclass(slots=True)
class Food:
    id: UUID
    name_en: str
    name_norm: str
    name_translations: dict[str, str]
    brand: str | None
    country: str | None
    portion_g: Decimal | None
    kcal: Decimal | None
    protein_g: Decimal | None
    carbs_g: Decimal | None
    fat_g: Decimal | None
    fiber_g: Decimal | None
    sugar_g: Decimal | None
    sodium_mg: Decimal | None
    sat_fat_g: Decimal | None
    micronutrients: dict | None
    barcode: str | None
    verified: bool
    source: str | None

    def translated_name(self, locale: str) -> str:
        return self.name_translations.get(locale) or self.name_en
