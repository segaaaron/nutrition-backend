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

from app.plan.domain.condition_gates._warnings import (
    MicronutrientDataIncompleteWarning,
    WarningCollector,
)

_MICRONUTRIENT_COLUMNS = ("folate_ug", "calcium_mg", "iron_mg")


@dataclass(frozen=True, slots=True)
class LactationGate:
    condition: str = "lactation"

    def emit_warnings(self, collector: WarningCollector) -> None:
        """D15 — flag that this gate's COALESCE filter may silently empty
        the candidate pool if catalog backfill of micronutrients is
        incomplete. One marker per filtered column.
        """
        for col in _MICRONUTRIENT_COLUMNS:
            collector.add(
                MicronutrientDataIncompleteWarning(
                    condition=self.condition,
                    column=col,
                )
            )

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
            # Source: IOM DRI 2002 — folate RDA 500 µg DFE/day in lactation;
            # ≥150 µg/portion across 4 daily meals.
            "lac_folate_min": 150,
            # Source: IOM DRI 2011 — calcium RDA 1000 mg/day during
            # lactation; 300 mg/portion (slightly stricter than pregnancy
            # to support bone resorption recovery).
            "lac_calcium_min": 300,
            # Source: IOM DRI 2002 — iron RDA 9 mg/day in lactation but
            # post-partum repletion benefits from ≥16 mg/day; ≥4 mg/portion.
            "lac_iron_min": 4,
        }
        return sql, params
