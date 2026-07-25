"""Physical macro sanity guard in _parse_items.

Invariant: protein_g + carbs_g + fat_g ≤ estimated_amount_g.
Violation = LLM hallucinated macros larger than the food itself weighs.
Guard scales macros down proportionally, then Atwater recomputes kcal.

Root-cause cases this guard fixes (from eval 2026-07-24):
  gs-snack-0004: nuez 30g → fat_g=130, kcal=1200  (4000 kcal/100g — impossible)
  gs-lunch-0007: carne 120g → fat_g=160, kcal=1440 (1200 kcal/100g — impossible)
"""
from __future__ import annotations

from app.vision.infrastructure.openai_vision import _parse_items


def _item_raw(
    name: str = "test",
    amount_g: float = 100.0,
    kcal: int = 200,
    protein_g: int = 20,
    carbs_g: int = 10,
    fat_g: int = 8,
    food_group: str = "protein",
    count: int = 1,
) -> dict:
    return {
        "items": [
            {
                "name": name,
                "count": count,
                "estimated_amount_g": amount_g,
                "kcal": kcal,
                "kcal_min": int(kcal * 0.8),
                "kcal_max": int(kcal * 1.2),
                "protein_g": protein_g,
                "carbs_g": carbs_g,
                "fat_g": fat_g,
                "fiber_g": 0,
                "sugar_g": 0,
                "confidence": 0.8,
                "food_group": food_group,
                "role": "main",
                "prep_method": "unknown",
                "bbox": None,
            }
        ]
    }


# ---------------------------------------------------------------------------
# Guard triggers — macros > food weight
# ---------------------------------------------------------------------------

def test_walnut_hallucination_clamped() -> None:
    """Real case: nuez 30g, fat_g=130 → kcal=1200. After guard: kcal ≤ 270 (30g × 9 kcal/g)."""
    items = _parse_items(_item_raw(
        name="nuez (mitad)",
        amount_g=30.0,
        kcal=1200,
        protein_g=4,
        carbs_g=2,
        fat_g=130,   # physically impossible: 130g fat in 30g food
        food_group="protein",
    ))
    it = items[0]
    # After macro scale-down: protein+carbs+fat ≤ 30g
    assert it.protein_g + it.carbs_g + it.fat_g <= 30
    # kcal must be physically plausible: max 9 kcal/g × 30g = 270 kcal
    assert it.kcal <= 270, f"kcal {it.kcal} still implausible for 30g"
    # Must be well above zero (nuts are calorie-dense)
    assert it.kcal > 50


def test_beef_stew_hallucination_clamped() -> None:
    """Real case: carne 120g, fat_g=160 → kcal=1440. After guard: kcal ≤ 1080 (120g × 9)."""
    items = _parse_items(_item_raw(
        name="carne guisada",
        amount_g=120.0,
        kcal=1440,
        protein_g=30,
        carbs_g=10,
        fat_g=160,   # physically impossible: 160g fat in 120g food
        food_group="protein",
    ))
    it = items[0]
    assert it.protein_g + it.carbs_g + it.fat_g <= 120
    assert it.kcal <= 1080, f"kcal {it.kcal} still implausible for 120g"
    assert it.kcal > 100


def test_macro_ratios_preserved_after_clamp() -> None:
    """Scale is proportional: if fat:protein:carbs = 10:2:1 before, same after."""
    items = _parse_items(_item_raw(
        name="overflow food",
        amount_g=50.0,
        kcal=900,
        protein_g=20,   # ratio 20:10:200 = 2:1:20
        carbs_g=10,
        fat_g=200,       # impossible for 50g food
        food_group="fat",
    ))
    it = items[0]
    macro_total = it.protein_g + it.carbs_g + it.fat_g
    assert macro_total <= 50
    # fat must still dominate (ratio preserved, only scale changed)
    assert it.fat_g > it.protein_g
    assert it.fat_g > it.carbs_g


# ---------------------------------------------------------------------------
# Guard does NOT trigger — normal realistic macros
# ---------------------------------------------------------------------------

def test_normal_chicken_breast_untouched() -> None:
    """100g pechuga: protein=22, fat=3, carbs=0 → sum=25 < 100g. No clamp."""
    items = _parse_items(_item_raw(
        name="pechuga de pollo",
        amount_g=150.0,
        kcal=180,
        protein_g=33,
        carbs_g=0,
        fat_g=4,
        food_group="protein",
    ))
    it = items[0]
    # sum = 37 << 150g — should be left untouched
    assert it.protein_g == 33
    assert it.carbs_g == 0
    assert it.fat_g == 4


def test_normal_rice_untouched() -> None:
    """Cooked rice 200g: protein=5, carbs=45, fat=1 → sum=51 < 200g. No clamp."""
    items = _parse_items(_item_raw(
        name="arroz blanco",
        amount_g=200.0,
        kcal=245,
        protein_g=5,
        carbs_g=45,
        fat_g=1,
        food_group="grain",
    ))
    it = items[0]
    assert it.protein_g == 5
    assert it.carbs_g == 45
    assert it.fat_g == 1


def test_dry_nuts_at_boundary_untouched() -> None:
    """Almonds 30g: protein=6, carbs=5, fat=14 → sum=25 < 30g. No clamp."""
    items = _parse_items(_item_raw(
        name="almendra",
        amount_g=30.0,
        kcal=174,
        protein_g=6,
        carbs_g=5,
        fat_g=14,
        food_group="protein",
    ))
    it = items[0]
    assert it.protein_g == 6
    assert it.fat_g == 14


def test_zero_macros_no_divide_by_zero() -> None:
    """Items with all-zero macros (pure water, spice) don't trigger guard or crash."""
    items = _parse_items(_item_raw(
        name="agua",
        amount_g=200.0,
        kcal=0,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        food_group="beverage",
    ))
    it = items[0]
    assert it.kcal == 0
    assert it.protein_g == 0
