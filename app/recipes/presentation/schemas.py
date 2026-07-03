"""Pydantic strict schemas for recipes/foods endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ComponentResponse(_Strict):
    id: UUID
    food_id: UUID | None
    sub_recipe_id: UUID | None
    free_text_name: str | None
    amount_g: Decimal | None
    modifier: str | None
    position: int


class RecipeResponse(_Strict):
    id: UUID
    name: str
    description: str | None
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
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"] | None
    prep_min: int | None
    instructions: list[str]
    regions: list[str]
    allergens: list[str]
    recommended_conditions: list[str]
    contraindicated_conditions: list[str]
    target_goals: list[str]
    components: list[ComponentResponse]
    score: float | None = None


class RecipeListResponse(_Strict):
    items: list[RecipeResponse]
    next_cursor: str | None


class RecipeSemanticSearchRequest(_Strict):
    q: str = Field(min_length=1, max_length=200)
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    # Filter lists: max 20 items each, each tag/region string max 64 chars.
    regions: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=20)
    allergens_exclude: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=20)
    conditions: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=20)
    tags: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=20)
    max_kcal: int | None = None
    min_protein_g: int | None = None
    target_goals: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


class FoodResponse(_Strict):
    id: UUID
    name: str
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
    barcode: str | None
    verified: bool
    score: float | None = None


class FoodListResponse(_Strict):
    items: list[FoodResponse]
    next_cursor: str | None
