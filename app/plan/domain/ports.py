"""Plan ports - repositories, selectors, and pipeline stage protocols.

The pipeline-stage protocols (Stage, RankingSignal, ConditionGate,
Constraint, Solver, WeightVectorRepo, TasteProfileReader) drive the
plan-generation pipeline. Implementations live in infrastructure or
application layers; this module declares contract only.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from app.plan.domain.entities import Plan
from app.recipes.domain.entities import Recipe

if TYPE_CHECKING:
    from app.plan.domain.context import (
        DraftPlan,
        MealSlot,
        PlanGenContext,
        RecipeView,
        Violation,
        WeightVector,
    )


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
        candidate_plan: list[dict[str, object]],
        alternatives_by_slot: dict[tuple[int, str], list[Recipe]],
    ) -> dict[str, object]: ...


# ---------------------------------------------------------------------------
# Pipeline-stage protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class TasteProfileReader(Protocol):
    """Reads a user's affinity for a recipe, scaled to [0, 1]."""

    async def affinity(self, user_id: UUID, recipe_id: UUID) -> Decimal: ...


@runtime_checkable
class WeightVectorRepo(Protocol):
    """Loads the ranking-signal weight vector for a given variant."""

    async def for_variant(self, variant_id: str) -> WeightVector: ...


@runtime_checkable
class Solver(Protocol):
    """Selects a final tuple of MealSlots from candidates + constraints."""

    async def solve(
        self,
        plan: DraftPlan,
        constraints: Sequence[Constraint],
        ctx: PlanGenContext,
    ) -> tuple[MealSlot, ...]: ...


@runtime_checkable
class Constraint(Protocol):
    """A hard or soft constraint evaluated against a DraftPlan."""

    name: str

    def check(self, plan: DraftPlan) -> list[Violation]: ...


@runtime_checkable
class ConditionGate(Protocol):
    """Mutates a recipe query to reflect a user-reported condition."""

    condition: str

    def contribute(self, q: RecipeQuery) -> RecipeQuery: ...


@runtime_checkable
class RankingSignal(Protocol):
    """A scalar signal scored per-recipe and combined via WeightVector."""

    key: str

    async def score(self, recipe: RecipeView, ctx: PlanGenContext) -> Decimal: ...


@runtime_checkable
class Stage(Protocol):
    """A single step of the plan-generation pipeline."""

    name: str

    async def apply(self, ctx: PlanGenContext) -> PlanGenContext: ...


class RecipeQuery(Protocol):
    """Opaque query object mutated by ConditionGate.contribute.

    Concrete shape lives in infrastructure (SQLAlchemy query builder, vector
    search payload, etc). The domain only requires that ConditionGates can
    receive and return one.
    """
