"""Pregnancy condition gate — H2.6 ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `pregnancy`:
  - `pregnancy_safe = TRUE` (no raw fish, no unpasteurized cheese,
    no high-Hg fish, no liver/organ, no alcohol — enforced via catalog flag).

Micronutrient thresholds (folate/iron/calcium) were originally included
but produced an empty candidate pool against the current general-nutrition
catalog (0/760 recipes met all three floors simultaneously). They are
deferred to a future specialized pregnancy catalog phase. Until then,
the `pregnancy_safe` flag is the single safety gate — set via SQL backfill
(`UPDATE recipes SET pregnancy_safe = true WHERE NOT tags && ARRAY['organ_meat',...]`)
executed 2026-07-05; all 760 current recipes pass.

NOVA scope: nutrition planning only. Trimester-aware kcal adjustment lives
in `app/plan/domain/bmr_safety.py::apply_trimester_adjustment`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PregnancyGate:
    condition: str = "pregnancy"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(r.pregnancy_safe = TRUE)"
        return sql, {}
