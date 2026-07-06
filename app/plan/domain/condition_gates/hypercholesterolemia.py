"""Hypercholesterolemia condition gate — ConditionGate Strategy.

Moves the inline Layer 1 hypercholesterolemia filter into the registry.

Source: 2018 AHA/ACC Cholesterol Guideline (Circulation 139:e1082) —
sat fat <6% kcal ≈ 5 g/meal at 2000 kcal × 3 meals.

NOVA scope: nutrition planning only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HypercholesterolemiaGate:
    condition: str = "hypercholesterolemia"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :hc_satfat_max)"
        params: dict[str, object] = {"hc_satfat_max": 5}
        return sql, params
