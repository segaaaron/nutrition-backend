"""Single source of truth for the macro-vs-kcal tolerance constant.

Cited by spec §6, by every gate-2 macro consistency check (catalog ingest
pipeline §20), by `MacroBreakdown.validate_tolerance`, and by the
clinical-nutrition-generator agent.

Never inline this value elsewhere — import it.
"""
from __future__ import annotations

from typing import Final

MACRO_TOLERANCE: Final[float] = 0.02
"""Relative tolerance between declared kcal and the macro-derived kcal.

`abs(kcal - (protein_g * 4 + carbs_g * 4 + fat_g * 9)) / kcal <= MACRO_TOLERANCE`
"""
