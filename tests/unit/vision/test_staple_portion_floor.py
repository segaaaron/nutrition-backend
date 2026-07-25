"""Unit — staple-portion floor (2026-07-14).

The LLM systematically under-estimates the grams of starchy sides. This floor
raises an implausibly-low staple portion to a conservative documented minimum,
scaling kcal + macros by the same factor (USDA per-gram value preserved), and
must NOT touch normal portions, non-staples, or garnishes.
"""
from __future__ import annotations

from decimal import Decimal

from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.plate_decomposition import (
    STAPLE_PORTION_FLOOR_G,
    floor_staple_portions,
)


def _item(name: str, grams: float, kcal: int, *, role: str = "side", **kw) -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal(str(grams)),
        kcal=kcal,
        protein_g=kw.get("protein_g", 3),
        carbs_g=kw.get("carbs_g", 20),
        fat_g=kw.get("fat_g", 5),
        confidence=0.8,
        food_group=kw.get("food_group", "grain"),
        role=role,
    )


def test_lifts_underestimated_fries() -> None:
    # Model says 60 g fries → floor 130 g. kcal scales by 130/60.
    it = _item("papas fritas", 60, 187, role="side")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 130.0
    assert out.kcal == round(187 * 130 / 60)  # per-gram preserved


def test_preserves_per_gram_value() -> None:
    it = _item("arroz blanco", 50, 65)  # 1.30 kcal/g
    out = floor_staple_portions([it])[0]
    before = it.kcal / float(it.estimated_amount_g)
    after = out.kcal / float(out.estimated_amount_g)
    assert abs(before - after) < 0.02  # USDA per-gram unchanged


def test_does_not_touch_normal_portion() -> None:
    it = _item("arroz", 200, 260)  # already a full serving
    out = floor_staple_portions([it])[0]
    assert out is it  # unchanged (no replace)


def test_ignores_non_staple() -> None:
    # "ensalada mixta" has no staple or protein floor marker → untouched.
    it = _item("ensalada mixta", 100, 30, role="main", food_group="vegetable")
    out = floor_staple_portions([it])[0]
    assert out is it


def test_protein_floor_lifts_underestimated_pechuga() -> None:
    # pechuga de pollo at 40 g for a main is under the 70 g floor → lifted.
    it = _item("pechuga de pollo", 40, 66, role="main", food_group="protein")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 70.0
    assert out.kcal == round(66 * (70 / 40))


def test_ignores_garnish_role() -> None:
    # rice as a decorative garnish must not be lifted to 130 g
    it = _item("arroz", 10, 13, role="garnish")
    out = floor_staple_portions([it])[0]
    assert out is it


def test_single_fried_egg_floor_applied() -> None:
    # huevo frito at 45 g for a main is under the 50 g egg floor → lifted.
    it = _item("huevo frito", 45, 81, role="main", food_group="protein")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 50.0


def test_single_fried_egg_above_floor_untouched() -> None:
    # huevo frito at 60 g is above the 50 g floor → untouched.
    it = _item("huevo frito", 60, 108, role="main", food_group="protein")
    out = floor_staple_portions([it])[0]
    assert out is it


def test_factor_capped_at_5x() -> None:
    # 5 g mislabeled blob → capped at 25 g, not 130 g.
    it = _item("papas fritas", 5, 16, role="side")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 25.0  # 5 * 5.0 cap


def test_scales_macros_and_range() -> None:
    it = DetectedFoodItem(
        name="fideos",
        estimated_amount_g=Decimal("65"),
        kcal=100,
        protein_g=4,
        carbs_g=20,
        fat_g=1,
        confidence=0.8,
        food_group="grain",
        role="main",
        kcal_min=80,
        kcal_max=120,
    )
    out = floor_staple_portions([it])[0]
    factor = 130 / 65  # 2.0
    assert out.carbs_g == round(20 * factor)
    assert out.kcal_min == round(80 * factor)
    assert out.kcal_max == round(120 * factor)


def test_floor_table_is_sane() -> None:
    # Starch floors: 90-160 g (below typical serving to avoid inflating normal ones).
    # Protein floors (added 2026-07-25): 50-80 g (single egg/shrimp = 50-80 g).
    assert all(50 <= g <= 160 for g in STAPLE_PORTION_FLOOR_G.values())
