"""Recipes ports — domain-level abstractions, infrastructure implements them."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.recipes.domain.entities import Food, Recipe
from app.recipes.domain.value_objects import FoodSearchQuery, RecipeSearchQuery


class RecipeRepository(Protocol):
    async def get(self, recipe_id: UUID, *, hydrate_components: bool = True) -> Recipe | None: ...

    async def get_many(self, recipe_ids: list[UUID]) -> list[Recipe]: ...

    async def search(self, query: RecipeSearchQuery) -> list[tuple[Recipe, float]]:
        """Returns ranked `(recipe, score)` pairs. Score is hybrid trigram+vector."""
        ...

    async def semantic_search(
        self, embedding: list[float], query: RecipeSearchQuery
    ) -> list[tuple[Recipe, float]]: ...


class FoodRepository(Protocol):
    async def get(self, food_id: UUID) -> Food | None: ...

    async def get_by_barcode(self, ean: str) -> Food | None: ...

    async def search(self, query: FoodSearchQuery) -> list[tuple[Food, float]]: ...


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]:
        """1536-dim text-embedding-3-large vector."""
        ...
