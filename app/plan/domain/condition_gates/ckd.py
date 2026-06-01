"""CKD condition gate — H2.3 ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `ckd` (chronic kidney
disease, declared by user; app does NOT diagnose):
  - `potassium_mg <= 400` per portion (strict — hyperkalemia risk is acute)
  - `phosphorus_mg <= 300` per portion
  - `sodium_mg <= 500` per portion
  - `protein_g <= 25` per portion (≈0.8 g/kg/day for 80kg over 3 meals)

Defensive COALESCE on micronutrient columns: NULL micros fail the threshold
(strict-positive) — safety > variety, same as lactation gate.

Catalog readiness (2026-06-01):
- 313 recipes `recommended_for: ckd` with K + P populated (round 1 + 2)
- 510 recipes `contraindicated_for: ckd`

NOVA scope: nutrition planning only. Mobile UI shows disclaimer. Layer 1
safety floor prevents harmful recipes regardless of advice scope.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CKDGate:
    condition: str = "ckd"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = (
            "(COALESCE(r.potassium_mg, 9999) <= :ckd_k_max"
            " AND COALESCE(r.phosphorus_mg, 9999) <= :ckd_p_max"
            " AND COALESCE(r.sodium_mg, 0) <= :ckd_na_max"
            " AND COALESCE(r.protein_g, 0) <= :ckd_protein_max)"
        )
        params: dict[str, object] = {
            "ckd_k_max": 400,
            "ckd_p_max": 300,
            "ckd_na_max": 500,
            "ckd_protein_max": 25,
        }
        return sql, params
