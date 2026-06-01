"""ADR-0015 — LiquidCap Constraint (Layer 4 coherence).

Caps the number of liquid meals per daily plan to preserve satiety.

| Goal           | Max liquid meals/day |
|----------------|----------------------|
| weight_loss    | 1                    |
| maintain       | 2                    |
| muscle_gain    | 2                    |
| weight_gain    | 2                    |
| health         | 2                    |

Pure domain — no I/O, no framework imports, Decimal-only math.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.plan.domain.context import DraftPlan, Violation


@dataclass(frozen=True, slots=True)
class LiquidCap:
    """Daily liquid-meal cap. Reads goal from plan.targets.goal."""

    name: str = "liquid_cap"

    def _max_allowed(self, goal: str) -> int:
        return 1 if goal == "weight_loss" else 2

    def check(self, plan: DraftPlan) -> list[Violation]:
        max_allowed = self._max_allowed(plan.targets.goal)
        n_liquid = sum(
            1 for slot in plan.meals if slot.recipe.meal_format == "liquid"
        )
        if n_liquid > max_allowed:
            return [
                Violation(
                    constraint=self.name,
                    magnitude=Decimal(n_liquid - max_allowed),
                    slot_index=None,
                )
            ]
        return []
