"""Fatty liver (NAFLD/NASH) condition gate — ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `fatty_liver` (non-alcoholic
fatty liver disease / steatohepatitis):

  - `added_sugar_g <= 8` per portion (added/free sugars drive de novo
    lipogenesis; fructose in particular is hepatotoxic at high doses).

    Corrected 2026-08-04. This clause used to read `sugar_g <= 8`, filtering
    TOTAL sugars against a threshold derived from FREE sugars. The two are not
    the same quantity, and `taste_profile.py` already said so about this very
    column: "the catalog's sugar_g column includes natural fruit sugars (total
    sugars, not added), so a hard gate would wrongly exclude healthy fruit
    dishes". The bug was invisible while a trigger defect left `sugar_g = 0` on
    1,466 recipes; once real values landed it began rejecting 53 fatty-liver
    breakfasts whose sugar is entirely intrinsic — yogurt, oats and fruit,
    exactly what NAFLD guidance recommends.

  - `sugar_g <= 30` per portion, or NULL — a fructose DOSE ceiling, not a
    free-sugar cap. Whole-fruit sugar is well tolerated, but a 57 g blended-
    fruit smoothie delivers fructose in one sitting at sugar-sweetened-beverage
    levels, where the source stops mattering (Jensen 2018). Above this ceiling
    the dish is excluded regardless of how natural its sugar is. Milder total-
    sugar variation is left to the Layer 3 ranking penalty
    (`taste_profile.sugar_penalty`, ramping 25 g to 45 g).
  - `sat_fat_g <= 5` per portion (saturated fat elevates hepatic steatosis
    independently of total kcal; Mediterranean pattern is first-line dietary
    therapy).
  - `fiber_g >= 3` per portion (fiber blunts postprandial glucose/insulin
    excursions and reduces hepatic de novo lipogenesis).
  - `sodium_mg <= 600` per portion or NULL (bias-admit: recipes without
    sodium data are admitted; those with confirmed high sodium are excluded).
    High sodium intake worsens portal hypertension and fluid retention in
    advanced NAFLD/NASH; EASL 2024 recommends <1500 mg/day for at-risk
    patients — ≈600 mg/meal across 3 main meals with snack margin).

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
  - Sodium: EASL Clinical Practice Guidelines 2024 — dietary sodium
    restriction to <1500 mg/day recommended in NAFLD with portal hypertension
    risk ⇒ ≈500 mg/meal at 3 meals → ceiling of 600 mg/recipe with margin.
    NULL sodium_mg is bias-admitted (catalog backfill in progress).

R6 fail-closed (2026-06-03): sugar_g and sat_fat_g are safety-critical for
NAFLD progression and MUST be present in the catalog row. Fiber uses
bias-admit (NULL → admitted) matching the sodium pattern — we cannot confirm
a recipe is low-fiber without data, and the `NOT refined_carbs` tag exclusion
provides a fallback safety signal. Recipes with confirmed low fiber (< 3g)
are still excluded. Rationale for R6 reversal: with ~95% of catalog rows
having NULL fiber_g, the original fail-closed rule shrinks the Bolivia +
fatty_liver pool to 6 breakfast / 5 snack — below the 7-per-slot minimum
required for a 7-day plan, causing plan generation to abort (2026-08-03).

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
        # R6 fail-closed on added_sugar_g and sat_fat_g (NAFLD-critical macros).
        # fiber_g uses COALESCE(., 0) so rows missing fiber data are
        # excluded — we are *promoting* fiber intake, NULL data → 0 → fail
        # the >=3 floor → excluded. Same bias as the diabetes_t2 fiber
        # promotion clause.
        sql = (
            "(r.added_sugar_g IS NOT NULL AND r.added_sugar_g <= :fl_added_sugar_max"
            " AND (r.sugar_g IS NULL OR r.sugar_g <= :fl_total_sugar_max)"
            " AND r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :fl_satfat_max"
            " AND (r.fiber_g IS NULL OR r.fiber_g >= :fl_fiber_min)"
            " AND (r.sodium_mg IS NULL OR r.sodium_mg <= :fl_sodium_max)"
            " AND NOT (r.tags && ARRAY['refined_carbs','high_fructose']::text[]))"
        )
        params: dict[str, object] = {
            # Source: AASLD 2023 + WHO 2015 free sugars <10 % kcal — ≈25 g/day
            # ⇒ ≈8 g/meal at 3 meals + snack margin. Fructose-driven hepatic
            # lipogenesis (Jensen 2018). Applied to added_sugar_g, NOT sugar_g:
            # the threshold is a free-sugar figure, and whole-fruit sugar was
            # never meant to count against it (corrected 2026-08-04).
            "fl_added_sugar_max": 8,
            # Fructose DOSE ceiling, distinct from the free-sugar cap above.
            # Moving the gate to added sugar correctly readmitted whole-fruit
            # dishes, but it also readmitted a 57 g-total-sugar mango-banana
            # smoothie. At that level the fructose delivered in one sitting is
            # in the sugar-sweetened-beverage range that Jensen 2018 implicates
            # in hepatic lipogenesis, and the source stops mattering. 30 g/meal
            # keeps an ordinary fruit-and-dairy breakfast while excluding the
            # blended-fruit outliers; it costs 14 recipes out of 192 at
            # breakfast and none at any other slot.
            "fl_total_sugar_max": 30,
            # Source: AASLD 2023 + 2018 AHA/ACC sat fat <7 % kcal ⇒ ≈15 g/day
            # at 2000 kcal ⇒ ≈5 g/meal at 3 meals.
            "fl_satfat_max": 5,
            # Source: USDA DGA 2020-2025 ≥25 g fiber/day + Plaz Torres 2019
            # Mediterranean evidence in NAFLD ⇒ ≈3 g/meal minimum floor.
            "fl_fiber_min": 3,
            # Source: EASL 2024 — <1500 mg/day sodium in NAFLD portal
            # hypertension risk ⇒ ≈500 mg/meal × 3 + snack margin = 600 mg cap.
            # Bias-admit: NULL sodium_mg rows are allowed through (catalog
            # backfill ongoing); only confirmed high-sodium rows are excluded.
            "fl_sodium_max": 600,
        }
        return sql, params
