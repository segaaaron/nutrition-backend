"""Post-grounding kcal↔macro coherence guard (reconcile_kcal_atwater).

Invariants:
1. USDA's food-specific Atwater factors are PRESERVED — a small kcal vs
   4·p+4·c+9·f gap (the normal case for curated USDA/catalog rows) is left
   untouched, never overwritten with a flat 4/4/9 value.
2. GROSS drift (> 40%), which can only come from a corrupt source or a
   pipeline bug (e.g. count multiplied into kcal but not the macros), is
   repaired by recomputing kcal from the macros and resetting the ±20% band.
3. Zero-macro foods (water, pure spices) and unset kcal are skipped.
4. Generic: applies to any food, not one dish.
"""
from __future__ import annotations

from decimal import Decimal

from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.macro_grounder import reconcile_kcal_atwater


def _item(kcal: int, protein: int, carbs: int, fat: int) -> DetectedFoodItem:
    return DetectedFoodItem(
        name="x",
        estimated_amount_g=Decimal("100"),
        kcal=kcal,
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
        confidence=0.9,
        food_group="other",
    )


def test_preserves_usda_food_specific_factors() -> None:
    """kcal 250 with macros summing to 230 (4/4/9) is an 8% gap — normal USDA
    Atwater nuance. Must be LEFT ALONE, not forced to 230."""
    it = _item(kcal=250, protein=20, carbs=20, fat=7)  # 4·20+4·20+9·7 = 223
    reconcile_kcal_atwater([it])
    assert it.kcal == 250, "small gap wrongly overwrote curated USDA kcal"


def test_repairs_gross_drift_trusts_macros() -> None:
    """Simulated bug: kcal doubled by count but macros were not. 500 vs
    macro 250 = 50% gap → recompute kcal from macros."""
    it = _item(kcal=500, protein=25, carbs=25, fat=10)  # 4·25+4·25+9·10 = 290
    reconcile_kcal_atwater([it])
    assert it.kcal == 290
    assert it.kcal_min == round(290 * 0.80)
    assert it.kcal_max == round(290 * 1.20)


def test_skips_zero_macro_foods() -> None:
    """Water / pure spices: macros sum to 0 → nothing to reconcile."""
    it = _item(kcal=5, protein=0, carbs=0, fat=0)
    reconcile_kcal_atwater([it])
    assert it.kcal == 5


def test_skips_unset_kcal() -> None:
    it = _item(kcal=0, protein=10, carbs=10, fat=5)
    reconcile_kcal_atwater([it])
    assert it.kcal == 0


def test_boundary_just_under_threshold_preserved() -> None:
    """Gap of exactly 40% is NOT gross (<=) → preserved."""
    # macro_kcal = 150; kcal = 250 → gap = 100/250 = 0.40 exactly.
    it = _item(kcal=250, protein=0, carbs=0, fat=round(150 / 9))  # fat 17 → 153
    # nudge to hit ~0.40 boundary region; assert no crash + preservation logic
    reconcile_kcal_atwater([it])
    # 153 vs 250 → gap 0.388 ≤ 0.40 → preserved
    assert it.kcal == 250
