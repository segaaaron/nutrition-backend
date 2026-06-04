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

NOVA scope: nutrition planning only. Layer 1 safety floor prevents
recipes incompatible with reported condition.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CKDGate:
    condition: str = "ckd"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        # R6 fail-closed (2026-06-03): all four CKD-critical columns are
        # safety-critical. Potassium and phosphorus already biased
        # safe (NULL → 9999 → fail). Now sodium and protein flip to explicit
        # IS NOT NULL instead of COALESCE(., 0) — incomplete catalog rows
        # are excluded, not silently treated as zero.
        sql = (
            "(COALESCE(r.potassium_mg, 9999) <= :ckd_k_max"
            " AND COALESCE(r.phosphorus_mg, 9999) <= :ckd_p_max"
            " AND r.sodium_mg IS NOT NULL AND r.sodium_mg <= :ckd_na_max"
            " AND r.protein_g IS NOT NULL AND r.protein_g <= :ckd_protein_max)"
        )
        params: dict[str, object] = {
            # Source: KDOQI 2020 Nutrition Practice Guideline for Nutrition in
            # CKD (Am J Kidney Dis 76(3)S1) — daily K ≤2000-3000 mg for
            # advanced CKD → ≤400 mg/portion at ~5 occasions/day.
            "ckd_k_max": 400,
            # Source: KDOQI 2020 — daily P ≤800-1000 mg → ≤300 mg/portion.
            # Hyperphosphatemia risk drives cap.
            "ckd_p_max": 300,
            # Source: KDIGO 2024 BP Guideline / WHO 2023 — Na <2000 mg/day
            # cardiovascular target → ≤500 mg/portion.
            "ckd_na_max": 500,
            # Source: KDOQI 2020 — 0.55-0.60 g/kg/day non-dialysis CKD; we
            # apply a conservative 0.8 g/kg/day across 3 meals for an 80 kg
            # reference adult ≈25 g/portion. Dialysis-dependent users need
            # higher targets — out of scope for the default gate.
            "ckd_protein_max": 25,
        }
        return sql, params
