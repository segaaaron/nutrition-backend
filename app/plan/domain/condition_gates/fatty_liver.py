"""Fatty liver (NAFLD/NASH) condition gate — ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `fatty_liver` (non-alcoholic
fatty liver disease / steatohepatitis):

  - `sugar_g <= 8` per portion (added/free sugars drive de novo lipogenesis;
    fructose in particular is hepatotoxic at high doses).
  - `sat_fat_g <= 5` per portion (saturated fat elevates hepatic steatosis
    independently of total kcal; Mediterranean pattern is first-line dietary
    therapy).
  - `fiber_g >= 3` per portion (fiber blunts postprandial glucose/insulin
    excursions and reduces hepatic de novo lipogenesis).

Per-meal thresholds derived from daily targets at ~2000 kcal across 3 main
meals with snack/condiment margin:

  - Sugar: AASLD 2023 + WHO 2015 — added sugars <10 % kcal, target ≈25 g/day
    free sugars in NAFLD → ≈8 g/meal (3 meals + snack margin). Fructose
    specifically implicated in hepatic lipogenesis (Jensen 2018,
    J Hepatol 68:1063).
  - Saturated fat: AASLD 2023 + 2018 AHA/ACC — sat fat <7 % kcal ⇒
    ≈15 g/day at 2000 kcal ⇒ ≈5 g/meal at 3 meals.
  - Fiber: target ≥25 g/day (USDA DGA 2020-2025; supported by Mediterranean
    pattern trials in NAFLD — Plaz Torres 2019, Nutrients 11:2971) ⇒
    ≈3 g/meal minimum across 4-6 daily occasions to drive intake floor.

R6 fail-closed (2026-06-03): sugar_g and sat_fat_g are safety-critical for
NAFLD progression and MUST be present in the catalog row. Fiber is bias-
include (NULL → 0 → recipe excluded) because we *promote* fiber-rich choices;
catalog rows missing fiber data are deferred to backfill rather than admitted.

Sources:
  - Rinella ME et al., AASLD Practice Guidance on the Clinical Assessment
    and Management of Nonalcoholic Fatty Liver Disease, Hepatology 2023;
    77(5):1797-1835. doi:10.1097/HEP.0000000000000323
  - Romero-Gómez M et al., Treatment of NAFLD with diet, physical activity
    and exercise, JAMA Intern Med 2019; 179(6):817.
  - Plaz Torres MC et al., Mediterranean Diet and NAFLD, Nutrients 2019;
    11(12):2971. doi:10.3390/nu11122971
  - Jensen T et al., Fructose and sugar: a major mediator of NAFLD,
    J Hepatol 2018; 68(5):1063-1075.

Catalog readiness (2026-06-09): no `recommended_for: fatty_liver` tagging
yet — gate operates purely on macro thresholds. Contraindicated-conditions
list and tag-based exclusions remain available for catalog curation.

NOVA scope: nutrition planning only. Layer 1 safety floor; no medical
diagnosis or pharmacological recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FattyLiverGate:
    condition: str = "fatty_liver"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        # R6 fail-closed on sugar_g and sat_fat_g (NAFLD-critical macros).
        # fiber_g uses COALESCE(., 0) so rows missing fiber data are
        # excluded — we are *promoting* fiber intake, NULL data → 0 → fail
        # the >=3 floor → excluded. Same bias as the diabetes_t2 fiber
        # promotion clause.
        sql = (
            "(r.sugar_g IS NOT NULL AND r.sugar_g <= :fl_sugar_max"
            " AND r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :fl_satfat_max"
            " AND COALESCE(r.fiber_g, 0) >= :fl_fiber_min"
            " AND NOT (r.tags && ARRAY['refined_carbs','high_fructose']::text[]))"
        )
        params: dict[str, object] = {
            # Source: AASLD 2023 + WHO 2015 free sugars <10 % kcal — ≈25 g/day
            # ⇒ ≈8 g/meal at 3 meals + snack margin. Fructose-driven hepatic
            # lipogenesis (Jensen 2018).
            "fl_sugar_max": 8,
            # Source: AASLD 2023 + 2018 AHA/ACC sat fat <7 % kcal ⇒ ≈15 g/day
            # at 2000 kcal ⇒ ≈5 g/meal at 3 meals.
            "fl_satfat_max": 5,
            # Source: USDA DGA 2020-2025 ≥25 g fiber/day + Plaz Torres 2019
            # Mediterranean evidence in NAFLD ⇒ ≈3 g/meal minimum floor.
            "fl_fiber_min": 3,
        }
        return sql, params
