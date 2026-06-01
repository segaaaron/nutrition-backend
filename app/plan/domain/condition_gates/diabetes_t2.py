"""Diabetes T2 condition gate — H2.2 ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `diabetes_t2`:
  - `sugar_g <= 15` per portion (existing inline gate, formalized here)
  - `carbs_g <= 45` per portion (master plan H2.1 cap)
  - `gl <= 10` per portion when populated (defensive COALESCE — NULL passes
    when catalog not yet backfilled; tightens once micros land)
  - `fiber_g >= 4` per portion (soluble fiber moderates glycemic response)

Catalog readiness (2026-06-01):
- 974 recipes `recommended_for: diabetes_t2`
- 24 recipes `contraindicated_for: diabetes_t2` (auto-derecommended round 1)
- Layer1 already had inline `sugar_g <= 15` gate; this Strategy formalizes
  the contract for explicit registry-based composition.

App scope: NOVA is a nutrition planner, not clinical advice. Disclaimer
shown via mobile UI (ADR-0017). Layer 1 safety floor prevents serving
high-glycemic recipes to declared diabetics regardless of advice scope.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiabetesT2Gate:
    condition: str = "diabetes_t2"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = (
            "(COALESCE(r.sugar_g, 0) <= :dt2_sugar_max"
            " AND COALESCE(r.carbs_g, 0) <= :dt2_carbs_max"
            " AND (r.gl IS NULL OR r.gl <= :dt2_gl_max)"
            " AND COALESCE(r.fiber_g, 0) >= :dt2_fiber_min)"
        )
        params: dict[str, object] = {
            "dt2_sugar_max": 15,
            "dt2_carbs_max": 45,
            "dt2_gl_max": 10,
            "dt2_fiber_min": 4,
        }
        return sql, params
