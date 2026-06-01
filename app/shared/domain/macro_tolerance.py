"""Single source of truth for macro math tolerance.

Cited by spec section 6, by every gate-2 macro consistency check (catalog
ingest pipeline section 20), by `MacroBreakdown.validate_tolerance`, by the
plan-generation pipeline coherence layer, and by the clinical-nutrition
generator agent.

Never inline these values elsewhere - import them.

All tolerances are Decimal to preserve the project-wide invariant that no
float appears in clinical math. Comparisons against int/float ratios are
permitted because `Decimal.__le__` accepts numeric types; only mixed
arithmetic raises `TypeError`.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Final

# kcal vs derived from (4 P + 4 C + 9 F) must agree within this fraction.
# Source: NOVA master plan invariant MacroConsistency. ADR pending.
MACRO_TOLERANCE: Final[Decimal] = Decimal("0.02")
"""Relative tolerance between declared kcal and the macro-derived kcal.

`abs(kcal - (protein_g * 4 + carbs_g * 4 + fat_g * 9)) / kcal <= MACRO_TOLERANCE`
"""

KCAL_TARGET_TOLERANCE: Final[Decimal] = Decimal("0.05")
"""Relative tolerance between a plan's total kcal and the user's kcal target."""

MACRO_SPLIT_TOLERANCE: Final[Decimal] = Decimal("0.05")
"""Relative tolerance between achieved and prescribed protein/carb/fat split."""
