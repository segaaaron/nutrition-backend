"""Lactation condition gate — H2.1 first ConditionGate Strategy.

Filters Layer 1 candidate recipes for users in `lactation`:
  - `pregnancy_safe = true` (same safe-set: no raw fish, soft cheese,
    high-Hg fish, alcohol, liver/organ)
  - `folate_ug >= 150` per portion (≥600 ug/day across 4 meals target)
  - `calcium_mg >= 300` per portion (≥1000 mg/day)
  - `iron_mg >= 4` per portion (≥16 mg/day)

These thresholds align with the 200 lactation-tagged recipes generated in
round 2 (`docs/algorithms/CATALOG_ROUND2_REPORT.md`).

Plain SQL fragment + parameter dict; Layer 1 composes contributions into the
final eligibility query.

Pre-migration safety: columns `folate_ug`, `calcium_mg`, `iron_mg`,
`pregnancy_safe` ship in alembic migration 0008. If the migration is not yet
applied on a target DB, the LEFT JOIN / NULL-coalesce style keeps the filter
defensive (passes when columns absent → enforced once migration applies).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LactationGate:
    condition: str = "lactation"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        """Return SQL fragment + params to AND into Layer 1 WHERE clause.

        Defensive NULL-tolerant: if a micronutrient column is NULL (recipe
        not yet backfilled), the recipe is rejected — lactation safety is
        strict-positive (must affirmatively meet thresholds).
        """
        sql = (
            "(r.pregnancy_safe = TRUE"
            " AND COALESCE(r.folate_ug, 0) >= :lac_folate_min"
            " AND COALESCE(r.calcium_mg, 0) >= :lac_calcium_min"
            " AND COALESCE(r.iron_mg, 0) >= :lac_iron_min)"
        )
        params: dict[str, object] = {
            "lac_folate_min": 150,
            "lac_calcium_min": 300,
            "lac_iron_min": 4,
        }
        return sql, params
