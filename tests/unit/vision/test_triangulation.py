"""Triangulation arbiter invariants (Fase 2) + hidden rules v2 (Fase 3)."""

from __future__ import annotations

from decimal import Decimal

from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.plate_decomposition import (
    floor_caloric_condiments,
    infer_hidden_dairy_and_oil,
)
from app.vision.domain.triangulation import (
    DishAnchor,
    arbitrate,
    clamp_to_physics,
    plausibility_band,
)


def _item(
    name: str,
    kcal: int,
    *,
    grams: float = 300.0,
    group: str = "protein",
    role: str | None = "main",
    prep: str | None = None,
) -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal(str(grams)),
        kcal=kcal,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=0.8,
        food_group=group,  # type: ignore[arg-type]
        role=role,
        prep_method=prep,
    )


# --- physics rails -------------------------------------------------------------


def test_physics_clamps_impossible_high() -> None:
    # 300 g of vegetables can't be 1800 kcal (band max 1.2 kcal/g → 360).
    it = clamp_to_physics(_item("ensalada", 1800, group="vegetable"))
    lo, hi = plausibility_band(it)
    assert it.kcal == hi


def test_physics_clamps_impossible_low() -> None:
    # 300 g of stew at 2 kcal is impossible (protein band min 0.8 → 240).
    it = clamp_to_physics(_item("guiso de res", 2))
    lo, _ = plausibility_band(it)
    assert it.kcal == lo


def test_physics_leaves_plausible_alone() -> None:
    assert clamp_to_physics(_item("lomo saltado", 450)).kcal == 450


# --- arbiter --------------------------------------------------------------------


def test_agreement_blends_and_narrows() -> None:
    # Bottom-up 500, catalog says 540 for same grams → agree → blend.
    anchor = DishAnchor(recipe_kcal=540, recipe_grams=300.0, similarity=0.8)
    out = arbitrate(_item("aji de gallina", 500), anchor)
    assert 500 <= out.kcal <= 540
    assert out.kcal_min is not None and out.kcal_max is not None
    width = (out.kcal_max - out.kcal_min) / out.kcal
    assert width <= 0.25  # narrowed: two independent paths agreed


def test_disagreement_physics_picks_plausible_anchor() -> None:
    # LLM said 1300 kcal for 300 g of stew (4.3 kcal/g — above protein
    # band max 4.5? no: plausible barely)... use vegetable: impossible.
    item = _item("ensalada rusa", 1400, group="vegetable")
    anchor = DishAnchor(recipe_kcal=320, recipe_grams=300.0, similarity=0.7)
    out = arbitrate(item, anchor)
    # Physics clamp fires first (1400 → band max 360), then anchor 320
    # agrees within 25% → blended ≈ 320-360.
    assert out.kcal <= 380


def test_weak_anchor_is_ignored() -> None:
    anchor = DishAnchor(recipe_kcal=900, recipe_grams=300.0, similarity=0.2)
    out = arbitrate(_item("plato", 450), anchor)
    assert out.kcal == 450


def test_both_plausible_disagreement_widens_range() -> None:
    anchor = DishAnchor(recipe_kcal=800, recipe_grams=300.0, similarity=0.8)
    out = arbitrate(_item("tallarin saltado", 450), anchor)
    assert out.kcal == 450  # bottom-up stands
    assert out.kcal_min is not None and out.kcal_min <= 450
    assert out.kcal_max is not None and out.kcal_max >= 800  # honest spread


# --- hidden rules v2 --------------------------------------------------------------


def test_cream_soup_gets_inferred_cream() -> None:
    items = [_item("crema de zapallo", 180, grams=400, group="vegetable")]
    out = infer_hidden_dairy_and_oil(items)
    assert len(out) == 2
    cream = out[-1]
    assert cream.inferred is True
    assert cream.food_group == "dairy"
    assert 40 <= cream.kcal <= 80


def test_cream_soup_with_dairy_listed_no_double_count() -> None:
    items = [
        _item("crema de zapallo", 180, grams=400, group="vegetable"),
        _item("crema de leche", 60, grams=30, group="dairy", role="sauce"),
    ]
    assert len(infer_hidden_dairy_and_oil(items)) == 2


def test_boiled_egg_does_not_suppress_frying_oil() -> None:
    # QA 2026-06-12 regression: substring "oil" matched "bOILed",
    # silently killing the hidden-oil inference for the fried item.
    from app.vision.domain.plate_decomposition import infer_hidden_cooking_fat

    items = [
        _item("fried chicken", 380, grams=200, group="protein", prep="deep_fried"),
        _item("boiled egg", 78, grams=50, group="protein", role="side", prep="boiled"),
    ]
    out = infer_hidden_cooking_fat(items)
    assert len(out) == 3
    assert out[-1].role == "cooking_fat"


def test_latam_rice_gets_oil() -> None:
    items = [_item("arroz blanco", 195, grams=150, group="grain", role="side", prep="boiled")]
    out = infer_hidden_dairy_and_oil(items)
    assert len(out) == 2
    assert out[-1].role == "cooking_fat"
    assert 25 <= out[-1].kcal <= 50


def test_mayo_kcal_floor_applied() -> None:
    items = [_item("mayonesa", 5, grams=12, group="fat", role="condiment")]
    out = floor_caloric_condiments(items)
    assert out[0].kcal >= 85


def test_salsa_criolla_low_kcal_is_legit_not_floored_below() -> None:
    # salsa criolla at 30 kcal for 40 g is above its floor (25) → untouched.
    items = [_item("salsa criolla", 30, grams=40, group="vegetable", role="condiment")]
    assert floor_caloric_condiments(items)[0].kcal == 30
