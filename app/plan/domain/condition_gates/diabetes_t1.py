"""Diabetes T1 condition gate — ConditionGate Strategy.

Dietary restrictions identical to T2D per ADA 2024 Standards of Care —
sugar control and carbohydrate consistency are required regardless of
insulin-dependence status. Layer 1 safety floor prevents high-glycemic
recipes from reaching T1D users.

NOVA scope: nutrition planning only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiabetesT1Gate:
    condition: str = "diabetes_t1"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = (
            "(r.sugar_g IS NOT NULL AND r.sugar_g <= :dt1_sugar_max"
            " AND r.carbs_g IS NOT NULL AND r.carbs_g <= :dt1_carbs_max"
            " AND (r.gl IS NULL OR r.gl <= :dt1_gl_max)"
            " AND COALESCE(r.fiber_g, 0) >= :dt1_fiber_min)"
        )
        params: dict[str, object] = {
            "dt1_sugar_max": 15,
            # ADA 2024: 45–60 g/meal is standard range. 60 g = upper end,
            # keeps lunch/dinner pools viable without losing glycemic control.
            "dt1_carbs_max": 60,
            "dt1_gl_max": 10,
            "dt1_fiber_min": 4,
        }
        return sql, params
