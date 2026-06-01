"""Pregnancy condition gate — H2.6 ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `pregnancy`:
  - `pregnancy_safe = TRUE` (no raw fish, no soft cheese unpasteurized,
    no high-Hg fish, no liver/organ, no alcohol)
  - `folate_ug >= 150` per portion (DRI: ≥600 ug/day = 150/portion across
    4 meals — pregnancy demands higher than lactation)
  - `iron_mg >= 4` per portion (DRI: ≥27 mg/day, harder to hit but the
    same per-portion floor as lactation given multiple meals)
  - `calcium_mg >= 250` per portion (DRI: ≥1000 mg/day)

Catalog readiness (2026-06-01):
- 0 recipes `recommended_for: pregnancy` (catalog generation pending)
- 26,827 recipes `pregnancy_safe = true` (baseline filter pool)

The +250 pregnancy-specific recipes are H2.2 backlog. Until then, Layer 1
filter still works against the 26,827 safe pool with strict micros.

NOVA scope: nutrition planning only. Mobile UI shows disclaimer + trimester
picker per mobile contract. Trimester-aware kcal adjustment lives in
`app/plan/domain/bmr_safety.py::apply_trimester_adjustment` (to be added).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PregnancyGate:
    condition: str = "pregnancy"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = (
            "(r.pregnancy_safe = TRUE"
            " AND COALESCE(r.folate_ug, 0) >= :preg_folate_min"
            " AND COALESCE(r.iron_mg, 0) >= :preg_iron_min"
            " AND COALESCE(r.calcium_mg, 0) >= :preg_calcium_min)"
        )
        params: dict[str, object] = {
            "preg_folate_min": 150,
            "preg_iron_min": 4,
            "preg_calcium_min": 250,
        }
        return sql, params
