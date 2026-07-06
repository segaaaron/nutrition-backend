"""Dyslipidemia condition gate — ConditionGate Strategy.

Dyslipidemia (elevated LDL/triglycerides) — same saturated-fat restriction
as hypercholesterolemia. The UI exposes this as a chip ("Colesterol alto /
Dislipidemia"), so users actively send this condition; it must have a gate.

Source: 2018 AHA/ACC Cholesterol Guideline (Circulation 139:e1082) —
saturated fat <6% kcal ≈ 5 g/meal at 2000 kcal × 3 meals.

NOVA scope: nutrition planning only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DyslipidemiaGate:
    condition: str = "dyslipidemia"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :dyslip_satfat_max)"
        params: dict[str, object] = {"dyslip_satfat_max": 5}
        return sql, params
