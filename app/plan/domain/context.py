"""Plan-generation pipeline value objects and immutable context.

All types here are frozen dataclasses or NamedTuples. Zero I/O. Zero
framework imports. Decimal-only math.

Cited by `app.plan.application.pipeline.Pipeline` and by every Stage,
Constraint, RankingSignal, ConditionGate implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal, NamedTuple
from uuid import UUID

# Goal label used by MacroTargets. ADR-0015 uses "weight_loss" to apply a
# stricter liquid-meal cap; other goals share the relaxed cap.
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
_VALID_GOALS: frozenset[str] = frozenset(
    {"weight_loss", "maintain", "muscle_gain", "weight_gain", "health"}
)


# ---------------------------------------------------------------------------
# Macro targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MacroTargets:
    """Daily macro targets computed for a user.

    All gram quantities are Decimal. `meals_per_day` controls how the daily
    kcal/protein totals are split across slots by the pipeline.
    """

    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    fiber_g_min: Decimal = Decimal("25")
    meals_per_day: int = 3
    goal: Goal = "maintain"

    def __post_init__(self) -> None:
        if self.goal not in _VALID_GOALS:
            raise ValueError(f"goal must be one of {sorted(_VALID_GOALS)}, got {self.goal!r}")
        if self.kcal < 0:
            raise ValueError("kcal must be >= 0")
        if self.protein_g < 0:
            raise ValueError("protein_g must be >= 0")
        if self.carbs_g < 0:
            raise ValueError("carbs_g must be >= 0")
        if self.fat_g < 0:
            raise ValueError("fat_g must be >= 0")
        if self.fiber_g_min < 0:
            raise ValueError("fiber_g_min must be >= 0")
        if not (1 <= self.meals_per_day <= 6):
            raise ValueError("meals_per_day must be in 1..6")

    def kcal_per_meal(self) -> Decimal:
        return self.kcal / Decimal(self.meals_per_day)

    def protein_per_meal(self) -> Decimal:
        return self.protein_g / Decimal(self.meals_per_day)

    def to_dict(self) -> dict[str, Decimal | int | str]:
        return {
            "kcal": self.kcal,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "fiber_g_min": self.fiber_g_min,
            "meals_per_day": self.meals_per_day,
            "goal": self.goal,
        }


# ---------------------------------------------------------------------------
# Constraint violation
# ---------------------------------------------------------------------------


class Violation(NamedTuple):
    """A single constraint violation reported by `Constraint.check`."""

    constraint: str
    magnitude: Decimal
    slot_index: int | None = None


# ---------------------------------------------------------------------------
# Weight vector
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WeightVector:
    """Per-variant ranking signal weights. Sum must equal 1.0 +/- 0.001."""

    variant_id: str
    weights: Mapping[str, Decimal]
    checksum: str

    def __post_init__(self) -> None:
        total: Decimal = Decimal("0")
        for value in self.weights.values():
            total += value
        if abs(total - Decimal("1.0")) > Decimal("0.001"):
            raise ValueError(f"WeightVector weights must sum to 1.0 +/- 0.001, got {total}")


# ---------------------------------------------------------------------------
# Stage audit trace
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StageTrace:
    """One row in the pipeline audit log."""

    stage_name: str
    duration_ms: int
    input_candidates: int
    output_candidates: int
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Recipe projection used by scoring + solver
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecipeView:
    """Denormalized recipe projection used during pipeline scoring.

    Kept intentionally minimal: only fields ranking/coherence stages read.
    """

    id: UUID
    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal
    sodium_mg: int
    sugar_g: Decimal
    sat_fat_g: Decimal
    gi: int | None
    tags: tuple[str, ...]
    allergens: tuple[str, ...]
    meal_time: str | None
    prep_min: int | None
    embedding: tuple[float, ...] | None = None
    # ADR-0015 — Layer 4 coherence reads this to apply the daily liquid cap.
    # Values: "solid" (default), "semi_solid", "liquid".
    meal_format: Literal["solid", "semi_solid", "liquid"] = "solid"


# ---------------------------------------------------------------------------
# Meal slot + draft plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MealSlot:
    """A single meal slot in the produced plan."""

    slot_index: int
    meal_time: str
    recipe: RecipeView


@dataclass(frozen=True, slots=True)
class DraftPlan:
    """An in-flight plan candidate evaluated by Constraints."""

    meals: tuple[MealSlot, ...]
    targets: MacroTargets

    def total_kcal(self) -> Decimal:
        total: Decimal = Decimal("0")
        for slot in self.meals:
            total += slot.recipe.kcal
        return total

    def total_macros(self) -> dict[str, Decimal]:
        protein: Decimal = Decimal("0")
        carbs: Decimal = Decimal("0")
        fat: Decimal = Decimal("0")
        fiber: Decimal = Decimal("0")
        for slot in self.meals:
            protein += slot.recipe.protein_g
            carbs += slot.recipe.carbs_g
            fat += slot.recipe.fat_g
            fiber += slot.recipe.fiber_g
        return {
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "fiber_g": fiber,
        }


# ---------------------------------------------------------------------------
# Pipeline context (immutable; threaded through every stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanGenContext:
    """Immutable context threaded through the plan-generation pipeline.

    Each Stage returns a *new* PlanGenContext via `dataclasses.replace`.
    """

    user_id: UUID
    targets: MacroTargets
    conditions: frozenset[str] = frozenset()
    allergens: frozenset[str] = frozenset()
    region: str = "latam"
    meal_times: tuple[str, ...] = ("breakfast", "lunch", "dinner")
    candidates_by_slot: Mapping[str, tuple[UUID, ...]] = field(default_factory=dict)
    scores: Mapping[UUID, Decimal] = field(default_factory=dict)
    selected: tuple[MealSlot, ...] = ()
    audit: tuple[StageTrace, ...] = ()
    budget_ms_remaining: int = 2000
    variant_id: str = "baseline"
    seed: int = 0
    algorithm_version: str = "0.1.0"
    generated_at: datetime | None = None

    def with_stage_trace(self, trace: StageTrace) -> PlanGenContext:
        return replace(
            self,
            audit=self.audit + (trace,),
            budget_ms_remaining=self.budget_ms_remaining - trace.duration_ms,
        )
