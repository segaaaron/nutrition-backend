"""Lactation condition gate — H2.1 ConditionGate Strategy.

Filters Layer 1 candidate recipes for users in `lactation`:

  1. `pregnancy_safe = TRUE` — same safe-set as pregnancy: no raw fish,
     no unpasteurized cheese, no organ meat, no alcohol preparations.

  2. NOT tagged `high_mercury_fish` — defense-in-depth exclusion.
     Methylmercury transfers into breast milk and accumulates in nursing
     infants. FDA/EPA advise breastfeeding mothers to avoid:
       shark (tiburón), swordfish (pez espada), king mackerel (caballa real),
       marlin (marlín), orange roughy, bigeye tuna, tilefish (blanquillo).
     Safe fish (salmon, trout, tilapia, shrimp) have no restrictions.
     Source: CDC Maternal Diet & Breastfeeding (2024);
             FDA/EPA Fish Advice (2017, updated 2024).

     Catalog status (2026-08-03): 0 active recipes tagged `high_mercury_fish`.

Micronutrient thresholds (folate/calcium/iron) produced an empty candidate
pool against the current general-nutrition catalog. Deferred to a future
specialized lactation catalog phase.

NOVA scope: nutrition planning only.

Sources:
  - CDC (2024). Maternal Diet and Breastfeeding. cdc.gov/breastfeeding-special-circumstances
  - FDA/EPA (2017). Advice about eating fish. Federal Register 82(12):6571.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LactationGate:
    condition: str = "lactation"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = (
            "(r.pregnancy_safe = TRUE"
            " AND NOT (r.tags && ARRAY['high_mercury_fish']::text[]))"
        )
        return sql, {}
