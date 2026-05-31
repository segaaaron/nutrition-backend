"""Recipes use cases. Application orchestration only — no SQL, no HTTP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.errors import NotFoundError
from app.recipes.domain.entities import Food, Recipe
from app.recipes.domain.ports import EmbeddingProvider, FoodRepository, RecipeRepository
from app.recipes.domain.value_objects import FoodSearchQuery, RecipeSearchQuery


@dataclass(slots=True)
class GetRecipe:
    recipes: RecipeRepository

    async def __call__(self, *, recipe_id: UUID, locale: str = "en") -> Recipe:
        rec = await self.recipes.get(recipe_id, hydrate_components=True)
        if rec is None:
            raise NotFoundError("recipe_not_found", recipe_id=str(recipe_id))
        return rec


@dataclass(slots=True)
class SearchRecipes:
    """Hybrid trigram + pgvector. Falls back to trigram-only if no embedder."""

    recipes: RecipeRepository
    embedder: EmbeddingProvider | None = None

    async def __call__(
        self, *, query: RecipeSearchQuery, semantic: bool = False
    ) -> list[tuple[Recipe, float]]:
        if semantic and query.q and self.embedder is not None:
            emb = await self.embedder.embed(query.q)
            return await self.recipes.semantic_search(emb, query)
        return await self.recipes.search(query)


@dataclass(slots=True)
class SwapRecipe:
    """Find substitutes constrained by allergens / macros (±10%) / region / meal_time."""

    recipes: RecipeRepository

    async def __call__(
        self, *, recipe_id: UUID, regions: list[str], allergens_exclude: list[str],
        conditions: list[str], k: int = 3,
    ) -> list[Recipe]:
        original = await self.recipes.get(recipe_id)
        if original is None:
            raise NotFoundError("recipe_not_found", recipe_id=str(recipe_id))

        kcal_low = int((original.kcal or 0) * 0.9) or None
        kcal_high = int((original.kcal or 0) * 1.1) or None
        protein_low = int((original.protein_g or 0) * 0.9) or None

        q = RecipeSearchQuery(
            meal_time=original.meal_time,
            regions=regions or original.regions,
            allergens_exclude=allergens_exclude,
            conditions=conditions,
            max_kcal=kcal_high,
            min_protein_g=protein_low,
            limit=k * 4,  # over-fetch, filter, trim
        )
        candidates = await self.recipes.search(q)
        out: list[Recipe] = []
        for rec, _ in candidates:
            if rec.id == recipe_id:
                continue
            if kcal_low and (rec.kcal or 0) < kcal_low:
                continue
            out.append(rec)
            if len(out) >= k:
                break
        return out


@dataclass(slots=True)
class GetAlternatives:
    """Top-K alternatives for plan-generation Layer-3 fan-out."""

    recipes: RecipeRepository

    async def __call__(
        self, *, query: RecipeSearchQuery, k: int = 20,
    ) -> list[tuple[Recipe, float]]:
        q = RecipeSearchQuery(
            q=query.q, meal_time=query.meal_time, regions=query.regions,
            allergens_exclude=query.allergens_exclude, conditions=query.conditions,
            tags=query.tags, max_kcal=query.max_kcal, min_protein_g=query.min_protein_g,
            ingredients_avoid=query.ingredients_avoid, target_goals=query.target_goals,
            limit=k,
        )
        return await self.recipes.search(q)


@dataclass(slots=True)
class GetFood:
    foods: FoodRepository

    async def __call__(self, *, food_id: UUID) -> Food:
        f = await self.foods.get(food_id)
        if f is None:
            raise NotFoundError("food_not_found", food_id=str(food_id))
        return f


@dataclass(slots=True)
class GetFoodByBarcode:
    foods: FoodRepository

    async def __call__(self, *, ean: str) -> Food:
        f = await self.foods.get_by_barcode(ean)
        if f is None:
            raise NotFoundError("food_not_found", barcode=ean)
        return f


@dataclass(slots=True)
class SearchFoods:
    foods: FoodRepository

    async def __call__(self, *, query: FoodSearchQuery) -> list[tuple[Food, float]]:
        return await self.foods.search(query)
