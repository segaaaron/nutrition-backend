"""Lactation condition gate — H2.1 first ConditionGate Strategy.

Filters Layer 1 candidate recipes for users in `lactation`:
  - `pregnancy_safe = true` (same safe-set as pregnancy: no raw fish,
    no unpasteurized cheese, no high-Hg fish, no alcohol, no organ meat).

Micronutrient thresholds (folate/calcium/iron) produced an empty candidate
pool against the current general-nutrition catalog (0/760 recipes meet all
three floors simultaneously). Deferred to a future specialized lactation
catalog phase. `pregnancy_safe` flag is the single safety gate for now.

NOVA scope: nutrition planning only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LactationGate:
    condition: str = "lactation"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(r.pregnancy_safe = TRUE)"
        return sql, {}
