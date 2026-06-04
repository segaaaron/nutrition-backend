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

NOVA scope: nutrition planning only. Layer 1 safety floor prevents serving
high-glycemic recipes to users who declared diabetes_t2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiabetesT2Gate:
    condition: str = "diabetes_t2"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        # R6 fail-closed (2026-06-03): sugar_g and carbs_g are safety-
        # critical for T2D and MUST be present in the catalog row. Glycemic
        # load (gl) and fiber_g remain bias-include (NULL → pass) because
        # micronutrient backfill lags; tightens once micros land (catalog
        # audit roadmap docs/ops/CATALOG_AUDIT.md).
        sql = (
            "(r.sugar_g IS NOT NULL AND r.sugar_g <= :dt2_sugar_max"
            " AND r.carbs_g IS NOT NULL AND r.carbs_g <= :dt2_carbs_max"
            " AND (r.gl IS NULL OR r.gl <= :dt2_gl_max)"
            " AND COALESCE(r.fiber_g, 0) >= :dt2_fiber_min)"
        )
        params: dict[str, object] = {
            # Source: ADA 2024 Standards of Care in Diabetes — added sugars
            # ≤10% kcal, ≈15 g per meal at ~2000 kcal/day, 4 meals.
            # https://diabetesjournals.org/care/issue/47/Supplement_1
            "dt2_sugar_max": 15,
            # Source: ADA 2024 — carbohydrate consistency, ≤45 g/meal aligns
            # with the lower-carb pattern endorsed for T2D adults.
            "dt2_carbs_max": 45,
            # Source: ADA 2024 + Brand-Miller 2003 (Am J Clin Nutr 77:5) on
            # glycemic load: per-meal GL ≤10 = "low GL" tier.
            "dt2_gl_max": 10,
            # Source: ADA 2024 — ≥25 g fiber/day target → ≈4 g/portion across
            # 4–6 daily eating occasions. Soluble fiber moderates postprandial
            # glucose excursion (Anderson 2009, Nutr Rev 67:188).
            "dt2_fiber_min": 4,
        }
        return sql, params
