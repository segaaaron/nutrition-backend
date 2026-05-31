"""Plan ports — repositories and selectors."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.plan.domain.entities import Plan
from app.recipes.domain.entities import Recipe


class PlanRepository(Protocol):
    async def get(self, plan_id: UUID, *, hydrate: bool = True) -> Plan | None: ...
    async def get_active(self, user_id: UUID) -> Plan | None: ...
    async def save(self, plan: Plan) -> Plan: ...
    async def update_meta(self, plan: Plan) -> None: ...
    async def mark_meal_completed(self, meal_id: UUID) -> None: ...
    async def swap_meal_recipe(self, meal_id: UUID, new_recipe_id: UUID) -> None: ...


class RecipeSelector(Protocol):
    """Composite port for Layer 1 → Layer 4 pipeline."""

    async def eligible(self, *, user_id: UUID, meal_time: str) -> list[UUID]: ...
    async def shortlist(
        self,
        *,
        candidate_ids: list[UUID],
        meal_time: str,
        kcal_target_share: int,
        protein_target_share: int,
        forbidden_ids: set[UUID],
        top_k: int = 20,
    ) -> list[tuple[UUID, float]]: ...
    async def rank(
        self,
        *,
        user_id: UUID,
        candidate_ids: list[UUID],
        meal_time: str,
    ) -> list[tuple[UUID, float]]: ...
    async def coherence_pass(
        self,
        *,
        user_id: UUID,
        candidate_plan: list[dict],
        alternatives_by_slot: dict[tuple[int, str], list[Recipe]],
    ) -> dict: ...
