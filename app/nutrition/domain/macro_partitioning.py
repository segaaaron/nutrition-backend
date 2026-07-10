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

# (protein g/kg, fat fraction of kcal) per goal.
# Protein sources: Helms 2014 (deficit 1.8), Morton 2018 (maintain 1.6),
# Phillips 2014 (muscle_gain 2.0), Wolfe 2008 (health 1.4 above RDA).
# Fat fraction sources: IOM AMDR 2005 (20-35%); we anchor at goal-specific
# 25-30% — weight_loss 25% to leave room for protein + satiety carbs,
# muscle_gain 25% same rationale, weight_gain 30% for energy density,
# health 30% Mediterranean-aligned (Estruch 2018 NEJM 378:e34).
_DEFAULTS: dict[Goal, tuple[float, float]] = {
    "weight_loss": (1.8, 0.25),
    "maintain": (1.6, 0.28),
    "muscle_gain": (2.0, 0.25),
    "weight_gain": (1.8, 0.30),
    "health": (1.4, 0.30),
}


@dataclass(frozen=True, slots=True)
class MacroBreakdownGrams:
    protein_g: int
    carbs_g: int
    fat_g: int

    def derived_kcal(self) -> int:
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9


def compute_macros(
    *,
    kcal_target: int,
    weight_kg: Decimal | float,
    goal: Goal,
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

    # Fallback: if protein + fat already overshoot kcal_target (high g/kg protein
    # on a low kcal target), carbs cannot go negative to compensate. In that
    # case, trim fat first (more elastic, 9 kcal/g), then protein, until
    # MACRO_TOLERANCE is satisfied. Both macros carry a nutritional floor:
    #   - fat 0.6 g/kg (hormone/steroidogenesis health — IOM AMDR floor rationale)
    #   - protein 1.2 g/kg (lean-mass preservation per protein RDA literature)
    # If the target is so low that even both floors overshoot tolerance, we stop
    # at the floors and accept the slight overshoot — a safety floor must never
    # be sacrificed to satisfy a soft ±2% kcal tolerance.
    derived = protein_g * 4 + carbs_g * 4 + fat_g * 9
    tolerance_kcal = float(kcal_target) * float(MACRO_TOLERANCE)
    protein_floor = int(round(1.2 * w))
    fat_floor = int(round(0.6 * w))
    while derived - kcal_target > tolerance_kcal:
        if fat_g > fat_floor:
            fat_g -= 1
        elif protein_g > protein_floor:
            protein_g -= 1
        else:
            break
        derived = protein_g * 4 + carbs_g * 4 + fat_g * 9

    return MacroBreakdownGrams(protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g)


def is_within_tolerance(brk: MacroBreakdownGrams, kcal_target: int) -> bool:
    if kcal_target <= 0:
        return False
    # Use Decimal throughout to avoid the float-1-ULP edge where `0.02` as
    # float is greater than `Decimal("0.02")` (returns False incorrectly).
    delta = Decimal(abs(brk.derived_kcal() - kcal_target))
    return delta / Decimal(kcal_target) <= MACRO_TOLERANCE
