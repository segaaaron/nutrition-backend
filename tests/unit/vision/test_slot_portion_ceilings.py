"""Unit tests for slot-aware portion ceilings (IMPROVEMENT 2, 2026-07-25).

Pure-function tests — no DB, no network.

Invariants:
1. SLOT_PORTION_CEIL_G["snack"] values are strictly less than
   FOOD_GROUP_PORTION_CEIL_G for every group (snack is never wider than lunch).
2. SLOT_PORTION_CEIL_G["breakfast"] values are <= FOOD_GROUP_PORTION_CEIL_G.
3. lunch/dinner entries in SLOT_PORTION_CEIL_G ARE FOOD_GROUP_PORTION_CEIL_G.
4. cap_implausible_portions(slot="snack") clamps a 300 g protein item to
   the snack ceiling, not the lunch ceiling.
5. cap_implausible_portions(slot=None) falls back to lunch/dinner ceilings.
6. decompose(slot="snack") propagates the slot down to cap_implausible_portions.
7. (Updated 2026-07-25 Fix-2) Slot ceiling is the final upper bound: when a slot
   is supplied, min(name_or_role_ceil, slot_group_ceil) is used so that named
   staples are still clamped by the tighter per-slot group ceiling.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.plate_decomposition import (
    FOOD_GROUP_PORTION_CEIL_G,
    SLOT_PORTION_CEIL_G,
    cap_implausible_portions,
    decompose,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(
    name: str = "test item",
    *,
    grams: float,
    kcal: int = 200,
    group: str = "protein",
    role: str = "main",
    protein: int = 30,
    carbs: int = 0,
    fat: int = 10,
    conf: float = 0.8,
) -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal(str(grams)),
        kcal=kcal,
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
        confidence=conf,
        food_group=group,  # type: ignore[arg-type]
        role=role,
    )


# ---------------------------------------------------------------------------
# 1. SLOT_PORTION_CEIL_G structure invariants
# ---------------------------------------------------------------------------


def test_snack_ceils_strictly_less_than_lunch_for_all_groups() -> None:
    snack = SLOT_PORTION_CEIL_G["snack"]
    lunch = SLOT_PORTION_CEIL_G["lunch"]
    for group in FOOD_GROUP_PORTION_CEIL_G:
        assert snack[group] < lunch[group], (
            f"Snack ceiling for '{group}' ({snack[group]}) must be strictly "
            f"below lunch ceiling ({lunch[group]})"
        )


def test_breakfast_ceils_not_greater_than_lunch_for_all_groups() -> None:
    breakfast = SLOT_PORTION_CEIL_G["breakfast"]
    lunch = SLOT_PORTION_CEIL_G["lunch"]
    for group in FOOD_GROUP_PORTION_CEIL_G:
        assert breakfast[group] <= lunch[group], (
            f"Breakfast ceiling for '{group}' ({breakfast[group]}) must be "
            f"<= lunch ceiling ({lunch[group]})"
        )


def test_lunch_and_dinner_use_food_group_portion_ceil_g() -> None:
    assert SLOT_PORTION_CEIL_G["lunch"] is FOOD_GROUP_PORTION_CEIL_G
    assert SLOT_PORTION_CEIL_G["dinner"] is FOOD_GROUP_PORTION_CEIL_G


def test_slot_ceils_cover_all_groups() -> None:
    required_groups = set(FOOD_GROUP_PORTION_CEIL_G)
    for slot_name, ceil_dict in SLOT_PORTION_CEIL_G.items():
        missing = required_groups - ceil_dict.keys()
        assert not missing, (
            f"SLOT_PORTION_CEIL_G['{slot_name}'] is missing groups: {missing}"
        )


# ---------------------------------------------------------------------------
# 2. Snack ceiling enforced: a 300 g protein item is clamped
# ---------------------------------------------------------------------------


def test_snack_caps_large_protein_item() -> None:
    """Use "tofu" — not in STAPLE_PORTION_CEIL_G, so only the group ceiling fires.
    Resolution order: name (miss) → role (main, miss) → group (snack protein 120 g).
    A 300 g tofu item in a snack must be clamped to the snack group ceiling."""
    snack_ceil = SLOT_PORTION_CEIL_G["snack"]["protein"]
    large_protein = _item("tofu", grams=300, kcal=480, group="protein")

    result = cap_implausible_portions([large_protein], slot="snack")

    assert len(result) == 1
    capped_g = float(result[0].estimated_amount_g)
    assert capped_g <= snack_ceil, (
        f"Expected snack protein to be clamped to {snack_ceil} g, got {capped_g} g"
    )
    # kcal must scale proportionally (not left at the original 480).
    assert result[0].kcal < 480


def test_snack_caps_large_grain_item() -> None:
    """Use "quinoa" — not in STAPLE_PORTION_CEIL_G, so only group ceiling fires.
    A 350 g quinoa item in a snack must be clamped to the snack grain ceiling (120 g)."""
    snack_ceil = SLOT_PORTION_CEIL_G["snack"]["grain"]
    large_grain = _item("quinoa cocida", grams=350, kcal=399, group="grain", protein=13, carbs=72, fat=6)

    result = cap_implausible_portions([large_grain], slot="snack")

    capped_g = float(result[0].estimated_amount_g)
    assert capped_g <= snack_ceil, (
        f"Expected snack grain to be clamped to {snack_ceil} g, got {capped_g} g"
    )


# ---------------------------------------------------------------------------
# 3. Without slot / lunch slot: full ceilings apply (no extra clamping)
# ---------------------------------------------------------------------------


def test_no_slot_uses_lunch_ceilings() -> None:
    """Use "carne guisada" — not in STAPLE_PORTION_CEIL_G, no role ceiling.
    A 280 g item is within the lunch protein ceiling (300 g) but above the
    snack ceiling (120 g).  With no slot it must NOT be clamped."""
    item = _item("carne guisada", grams=280, kcal=462, group="protein")
    result_no_slot = cap_implausible_portions([item], slot=None)
    result_lunch = cap_implausible_portions([item], slot="lunch")

    # Neither should clamp (280 < 300 lunch ceiling).
    assert float(result_no_slot[0].estimated_amount_g) == pytest.approx(280.0)
    assert float(result_lunch[0].estimated_amount_g) == pytest.approx(280.0)


def test_lunch_slot_does_not_clamp_normal_portion() -> None:
    item = _item("salmón", grams=180, kcal=297, group="protein")
    result = cap_implausible_portions([item], slot="lunch")
    # salmón has a named ceiling of 220 g — 180 g is fine.
    assert float(result[0].estimated_amount_g) == pytest.approx(180.0)


# ---------------------------------------------------------------------------
# 4. Named staple ceilings survive slot narrowing
# ---------------------------------------------------------------------------


def test_staple_named_ceiling_still_applies_in_snack() -> None:
    """Fix-2 (2026-07-25): slot ceiling is the final upper bound even when a
    name ceiling fires first.  450 g arroz: name-ceiling = 400 g, but snack
    grain group ceiling = 120 g → result must be min(400, 120) = 120 g.
    A 400-g arroz serving is ~520 kcal, which far exceeds any snack budget."""
    snack_grain_ceil = SLOT_PORTION_CEIL_G["snack"]["grain"]
    large_rice = _item("arroz", grams=450, kcal=585, group="grain", carbs=100)
    result = cap_implausible_portions([large_rice], slot="snack")
    # Slot ceiling (120 g for snack grain) takes the final min().
    assert float(result[0].estimated_amount_g) == pytest.approx(float(snack_grain_ceil))


# ---------------------------------------------------------------------------
# 5. decompose propagates slot
# ---------------------------------------------------------------------------


def test_decompose_slot_snack_caps_large_protein() -> None:
    snack_ceil = SLOT_PORTION_CEIL_G["snack"]["protein"]
    # Use a simple clean protein item (no frying, no sauce, no spice) so
    # only cap_implausible_portions affects the grams.
    item = _item(
        "queso fresco",
        grams=250,
        kcal=700,
        group="protein",
        role="main",
        protein=50,
        carbs=5,
        fat=55,
    )
    items_out, totals = decompose([item], slot="snack")
    protein_items = [i for i in items_out if i.food_group == "protein"]
    assert protein_items, "protein item should survive decompose"
    capped_g = float(protein_items[0].estimated_amount_g)
    assert capped_g <= snack_ceil, (
        f"decompose(slot='snack') should cap protein to {snack_ceil} g, got {capped_g}"
    )


def test_decompose_no_slot_leaves_normal_lunch_portion_intact() -> None:
    item = _item(
        "pechuga a la plancha",
        grams=150,
        kcal=248,
        group="protein",
        role="main",
        protein=46,
        carbs=0,
        fat=5,
    )
    items_out, _ = decompose([item])
    protein_items = [i for i in items_out if i.food_group == "protein"]
    assert protein_items
    # 150 g is well within all ceilings; must not be touched.
    assert float(protein_items[0].estimated_amount_g) == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# 6. Snack ceiling for beverages: a 600 ml drink is reduced
# ---------------------------------------------------------------------------


def test_snack_caps_large_beverage() -> None:
    snack_bev_ceil = SLOT_PORTION_CEIL_G["snack"]["beverage"]
    large_drink = _item("jugo de naranja", grams=600, kcal=276, group="beverage", protein=0, carbs=69, fat=0)
    result = cap_implausible_portions([large_drink], slot="snack")
    capped_g = float(result[0].estimated_amount_g)
    assert capped_g <= snack_bev_ceil


# ---------------------------------------------------------------------------
# 7. Unknown / novel slot falls back to lunch ceilings gracefully
# ---------------------------------------------------------------------------


def test_unknown_slot_falls_back_to_lunch_ceilings() -> None:
    item = _item("tofu", grams=280, kcal=280, group="protein")
    result = cap_implausible_portions([item], slot="teatime")  # not in SLOT_PORTION_CEIL_G
    # Falls back to FOOD_GROUP_PORTION_CEIL_G["protein"] = 300 g → no clamp.
    assert float(result[0].estimated_amount_g) == pytest.approx(280.0)


# ---------------------------------------------------------------------------
# 8. QA gate findings (2026-07-25) — known gaps, tracked as strict xfail so the
#    suite goes green the moment they are fixed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "grams", "group", "role"),
    [
        ("arroz", 400.0, "grain", "side"),          # staple name ceiling 400 vs snack grain 120
        ("papas fritas", 400.0, "grain", "side"),   # staple name ceiling 400 vs snack grain 120
        ("pollo a la plancha", 200.0, "protein", "main"),  # name 200 vs snack protein 120
        ("aderezo", 150.0, "fat", "garnish"),       # role 150 vs snack fat 35
    ],
)
def test_snack_slot_also_tightens_named_and_role_ceilings(
    name: str, grams: float, group: str, role: str
) -> None:
    snack_ceil = SLOT_PORTION_CEIL_G["snack"][group]
    item = _item(name, grams=grams, group=group, role=role)

    result = cap_implausible_portions([item], slot="snack")

    assert float(result[0].estimated_amount_g) <= snack_ceil, (
        f"{name!r} at {grams} g in a snack should be clamped to the snack "
        f"{group} ceiling ({snack_ceil} g), got {result[0].estimated_amount_g} g"
    )


@pytest.mark.parametrize("slot", ["SNACK", "Snack", " snack", "snack "])
def test_slot_lookup_is_case_and_whitespace_insensitive(slot: str) -> None:
    snack_ceil = SLOT_PORTION_CEIL_G["snack"]["protein"]
    item = _item("tofu", grams=300, kcal=480, group="protein")

    result = cap_implausible_portions([item], slot=slot)

    assert float(result[0].estimated_amount_g) <= snack_ceil, (
        f"slot={slot!r} should resolve to the snack rails ({snack_ceil} g), "
        f"got {result[0].estimated_amount_g} g"
    )
