"""Pregnancy condition gate — H2.6 ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `pregnancy`:

  1. `pregnancy_safe = TRUE` — catalog flag set via SQL backfill (2026-07-05).
     Covers: no raw fish, no unpasteurized cheese, no liver/organ meat,
     no alcohol-based preparations.

  2. NOT tagged `high_mercury_fish` — defense-in-depth exclusion for recipes
     containing methylmercury-heavy species. FDA/EPA + ACOG explicitly
     prohibit for pregnant women:
       shark (tiburón), swordfish (pez espada), king mackerel (caballa real),
       marlin (marlín), orange roughy, bigeye tuna, tilefish (blanquillo).
     Methylmercury crosses the placenta and damages fetal CNS development.
     Source: FDA/EPA 2017 Fish Advice; ACOG Committee Opinion 2021.

     Catalog status (2026-08-03): 0 active recipes tagged `high_mercury_fish`.
     Tag check is defense-in-depth — blocks future additions before they
     reach pregnant users. Any new recipe with the above species MUST be
     tagged `high_mercury_fish` at insert time.

Micronutrient thresholds (folate/iron/calcium) were originally included
but produced an empty candidate pool against the current general-nutrition
catalog (0/1200 recipes meet all three floors simultaneously). Deferred to
a future specialized pregnancy catalog phase.

NOVA scope: nutrition planning only. Trimester-aware kcal adjustment lives
in `app/plan/domain/bmr_safety.py::apply_trimester_adjustment`.

Sources:
  - FDA/EPA (2017). Advice about eating fish. Federal Register 82(12):6571.
  - ACOG Committee Opinion No. 800 (2021). Micronutrients during pregnancy.
  - WHO (2023). Mercury and health. https://www.who.int/news-room/fact-sheets/detail/mercury-and-health
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PregnancyGate:
    condition: str = "pregnancy"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = (
            "(r.pregnancy_safe = TRUE"
            " AND NOT (r.tags && ARRAY['high_mercury_fish']::text[]))"
        )
        return sql, {}
