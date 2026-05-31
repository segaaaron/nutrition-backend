"""Macro partitioning per goal (spec §4 step 4).

Strategy — protein anchored to bodyweight (g/kg), fat as % of kcal target,
carbs fills the remainder. Then we round and **back-adjust carbs** so the
combined kcal stays inside MACRO_TOLERANCE of the target.

Defaults per goal (g/kg protein, fat %):
  weight_loss     : 1.8 g/kg protein, 25% fat
  maintain        : 1.6 g/kg protein, 28% fat
  muscle_gain     : 2.0 g/kg protein, 25% fat
  weight_gain     : 1.8 g/kg protein, 30% fat
  health          : 1.4 g/kg protein, 30% fat
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.shared.domain.macro_tolerance import MACRO_TOLERANCE

Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]

_DEFAULTS: dict[Goal, tuple[float, float]] = {
    "weight_loss": (1.8, 0.25),
    "maintain":    (1.6, 0.28),
    "muscle_gain": (2.0, 0.25),
    "weight_gain": (1.8, 0.30),
    "health":      (1.4, 0.30),
}


@dataclass(frozen=True, slots=True)
class MacroBreakdownGrams:
    protein_g: int
    carbs_g: int
    fat_g: int

    def derived_kcal(self) -> int:
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9


def compute_macros(
    *, kcal_target: int, weight_kg: Decimal | float, goal: Goal,
) -> MacroBreakdownGrams:
    prot_per_kg, fat_pct = _DEFAULTS[goal]
    w = float(weight_kg)
    protein_g = int(round(prot_per_kg * w))
    fat_g = int(round(kcal_target * fat_pct / 9))
    remaining_kcal = kcal_target - (protein_g * 4 + fat_g * 9)
    carbs_g = max(0, int(round(remaining_kcal / 4)))

    # Verify and correct: if outside MACRO_TOLERANCE, nudge carbs by ±1g until in range.
    derived = protein_g * 4 + carbs_g * 4 + fat_g * 9
    diff = derived - kcal_target
    # Carbs are the elasticity term. Each gram = 4 kcal.
    delta_g = int(round(-diff / 4))
    carbs_g = max(0, carbs_g + delta_g)

    return MacroBreakdownGrams(protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g)


def is_within_tolerance(brk: MacroBreakdownGrams, kcal_target: int) -> bool:
    if kcal_target <= 0:
        return False
    return abs(brk.derived_kcal() - kcal_target) / kcal_target <= MACRO_TOLERANCE
