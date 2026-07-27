"""Plate Decomposition 2.0 invariants.

1. Dry spices (comino, pimienta, ají seco…) clamp to ≤5 kcal — the LLM
   hallucinating 35 kcal for a pinch of cumin must not inflate the plate.
2. Caloric condiments (ají en aceite, mayonesa) are NEVER clamped.
3. Fried items without a listed fat component get an inferred cooking-oil
   item (flagged, low-confidence); when fat IS listed, nothing is added.
4. Totals: kcal_min ≤ kcal ≤ kcal_max always; ranges derived from
   confidence when the LLM omitted them.
5. Old cached JSONB rows (no v2 fields) still deserialize.
"""

from __future__ import annotations

from decimal import Decimal

from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.plate_decomposition import (
    DRY_SPICE_KCAL_CAP,
    SLOT_KCAL_MAX,
    clamp_dry_spices,
    clamp_meal_total_kcal,
    compute_totals,
    decompose,
    infer_hidden_cooking_fat,
    is_dry_spice,
)
from app.vision.infrastructure.repositories import _items_from_jsonb


def _item(
    name: str,
    kcal: int,
    *,
    grams: float = 100.0,
    role: str | None = None,
    prep: str | None = None,
    fat: int = 0,
    conf: float = 0.8,
    kcal_min: int | None = None,
    kcal_max: int | None = None,
) -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal(str(grams)),
        kcal=kcal,
        protein_g=0,
        carbs_g=0,
        fat_g=fat,
        confidence=conf,
        food_group="other",
        role=role,
        prep_method=prep,
        kcal_min=kcal_min,
        kcal_max=kcal_max,
    )


# --- 1+2: spice clamp vs caloric condiments --------------------------------


def test_dry_spice_kcal_hallucination_is_clamped() -> None:
    sopa = [
        _item("sopa de pollo", 320, grams=400, role="main", prep="stewed"),
        _item("comino molido", 35, grams=2, role="condiment", prep="raw"),
        _item("pimienta negra", 20, grams=1, role="condiment", prep="raw"),
    ]
    out = clamp_dry_spices(sopa)
    assert out[1].kcal <= DRY_SPICE_KCAL_CAP
    assert out[2].kcal <= DRY_SPICE_KCAL_CAP
    assert out[0].kcal == 320  # main untouched


def test_caloric_condiments_are_never_clamped() -> None:
    items = [
        _item("aji en aceite", 45, grams=15, role="condiment", fat=4),
        _item("mayonesa", 90, grams=12, role="condiment", fat=10),
        _item("salsa criolla", 30, grams=40, role="sauce"),
    ]
    out = clamp_dry_spices(items)
    assert [i.kcal for i in out] == [45, 90, 30]


def test_is_dry_spice_matches_multiword_and_accents() -> None:
    assert is_dry_spice("Comino molido")
    assert is_dry_spice("pimienta negra")
    assert is_dry_spice("ají seco")  # accent-stripped
    assert not is_dry_spice("aji en aceite con sal")  # caloric prep


# --- 3: hidden cooking fat ---------------------------------------------------


def test_fried_without_fat_gets_inferred_oil() -> None:
    items = [
        _item("milanesa de pollo", 380, grams=200, role="main", prep="deep_fried"),
        _item("papas fritas", 310, grams=150, role="side", prep="fried"),
    ]
    out = infer_hidden_cooking_fat(items)
    assert len(out) == 3
    oil = out[-1]
    assert oil.inferred is True
    assert oil.role == "cooking_fat"
    # 200*0.12 + 150*0.10 = 39 g → ~345 kcal
    assert float(oil.estimated_amount_g) == 39.0
    assert oil.kcal > 300
    # Low confidence → stays below the 0.7 auto-insert threshold.
    assert oil.confidence < 0.7


def test_no_oil_added_when_fat_already_listed() -> None:
    items = [
        _item("milanesa", 380, grams=200, role="main", prep="deep_fried"),
        _item("aceite vegetal", 180, grams=20, role="cooking_fat", fat=20),
    ]
    assert len(infer_hidden_cooking_fat(items)) == 2


def test_no_oil_added_for_boiled_or_raw() -> None:
    items = [
        _item("pollo sancochado", 250, grams=200, role="main", prep="boiled"),
        _item("ensalada", 40, grams=120, role="side", prep="raw"),
    ]
    assert len(infer_hidden_cooking_fat(items)) == 2


# --- 4: totals ----------------------------------------------------------------


def test_totals_bracket_best_estimate() -> None:
    items = [
        _item("arroz", 260, grams=200, kcal_min=220, kcal_max=300),
        _item("pollo a la plancha", 240, grams=150, conf=0.4),  # range derived
    ]
    totals = compute_totals(items)
    assert totals.kcal_min <= totals.kcal <= totals.kcal_max
    assert totals.kcal == 500
    assert totals.kcal_min < 500 < totals.kcal_max


def test_totals_empty_plate_is_zero() -> None:
    t = compute_totals([])
    assert (t.kcal_min, t.kcal, t.kcal_max) == (0, 0, 0)


def test_decompose_full_pipeline_soup_example() -> None:
    """Sopa con especias + ají: especias ~0 kcal, ají en aceite cuenta,
    totales con rango."""
    items = [
        _item("sopa criolla", 350, grams=450, role="main", prep="stewed"),
        _item("comino", 30, grams=2, role="condiment"),
        _item("aji en aceite", 45, grams=15, role="condiment", fat=4),
    ]
    out, totals = decompose(items)
    by_name = {i.name: i for i in out}
    assert by_name["comino"].kcal <= DRY_SPICE_KCAL_CAP
    assert by_name["aji en aceite"].kcal == 45
    assert totals.kcal == 350 + by_name["comino"].kcal + 45
    assert totals.kcal_min <= totals.kcal <= totals.kcal_max


# --- 5: backward-compat deserialization ---------------------------------------


def test_pre_v2_cached_jsonb_rows_still_deserialize() -> None:
    legacy = [
        {
            "name": "ensalada",
            "estimated_amount_g": 120.0,
            "kcal": 60,
            "protein_g": 2,
            "carbs_g": 8,
            "fat_g": 3,
            "confidence": 0.9,
            "food_group": "vegetable",
            "matched_food_id": None,
            "matched_name_norm": None,
            "match_method": None,
            # no role / prep_method / kcal_min / kcal_max / inferred
        }
    ]
    items = _items_from_jsonb(legacy)
    assert len(items) == 1
    it = items[0]
    assert it.role is None
    assert it.prep_method is None
    assert it.kcal_min is None
    assert it.inferred is False


# ── Portion ceiling (cap_implausible_portions) — high-side mirror of the floor ──
def test_cap_trims_grossly_over_estimated_garnish() -> None:
    """A garnish read as 400 g is implausible → clamped to the role ceiling
    (150 g), with kcal scaled by the same factor (USDA per-gram preserved)."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("aros de cebolla", 400, grams=400.0, role="garnish")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 150.0
    assert out.kcal == 150  # 400 * (150/400)


def test_cap_leaves_normal_portions_untouched() -> None:
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("papas fritas", 300, grams=180.0, role="side")  # 180 g < 400 ceil
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 180.0
    assert out.kcal == 300


def test_cap_clamps_staple_over_ceiling() -> None:
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("arroz", 800, grams=800.0, role="main")  # 800 g > 400 ceil
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 400.0
    assert out.kcal == 400  # 800 * 0.5


def test_cap_normal_main_under_group_ceiling_untouched() -> None:
    """A normal 'main' with no staple marker and no role ceiling now falls back
    to the GENERIC food_group ceiling — but a normal 300 g portion is well under
    it, so it is left untouched. Proves the generic net does not over-clamp."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("guiso de res", 480, grams=300.0, role="main")  # group "other" → 400 g
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 300.0


def test_cap_generic_group_backstop_catches_unlisted_food() -> None:
    """THE fix for the bun-bug class: an un-whitelisted food (no name marker, no
    small role) is NO LONGER uncapped. A 'main' grain read at 900 g is clamped by
    the generic food_group='grain' ceiling (350 g, tightened 2026-07-25). Nothing
    falls through."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = DetectedFoodItem(
        name="tamal gigante",  # not in any name list
        estimated_amount_g=Decimal("900"),
        kcal=1800,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=0.8,
        food_group="grain",
        role="main",  # not a small-role ceiling
        prep_method=None,
        kcal_min=None,
        kcal_max=None,
    )
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 350.0  # generic grain ceiling (tightened)
    assert out.kcal == 700  # 1800 * (350/900)


def test_cap_clamps_over_estimated_hamburger_bun() -> None:
    """Regression (PROD 2026-07-17): same burger photo, the LLM read the bun as
    200 g (→544 kcal) some calls and 80 g (→218 kcal) others. Bun is role='main'
    food_group='grain' → previously uncapped. Ceiling 130 g clamps the 200 g
    overshoot; USDA per-gram value is preserved by scaling kcal by the factor."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("pan de hamburguesa", 544, grams=200.0, role="main")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 130.0
    assert out.kcal == 354  # 544 * (130/200) = 353.6 → 354


def test_cap_leaves_normal_hamburger_bun_untouched() -> None:
    """The correct 80 g bun (218 kcal) is below the 130 g ceiling → untouched.
    Proves the fix clamps only the outlier, never a normal-sized bun."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("pan de hamburguesa", 218, grams=80.0, role="main")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 80.0
    assert out.kcal == 218


def test_cap_never_clamps_generic_bread() -> None:
    """A generic 'pan' (e.g. a baguette/marraqueta) legitimately weighs ~250 g.
    The bun markers are specific ('pan de hamburguesa'), so generic bread is
    NEVER clamped — no over-correction of legitimate large bread portions."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("pan frances", 660, grams=250.0, role="main")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 250.0
    assert out.kcal == 660


def test_cap_clamps_chicken_count_hallucination() -> None:
    """Regression (gs-dinner-0003): LLM assigns count=8 × 70g = 560g for pizza
    chicken topping, already capped to 500g by protein group. 'pollo' ceiling
    200g fires first (STAPLE > group) and clamps the remaining overshoot.
    kcal scaled proportionally so USDA per-gram density is preserved."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("pollo a la plancha", 864, grams=500.0, role="main")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 200.0
    # 864 * (200/500) = 345.6 → rounds to 346
    assert out.kcal == 346


def test_cap_leaves_normal_chicken_breast_untouched() -> None:
    """A realistic single chicken breast (180g, 300 kcal) is below the 200g
    ceiling and must not be clamped — only gross overshoots fire."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("pollo sazonado al horno", 300, grams=180.0, role="main")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 180.0
    assert out.kcal == 300


def test_cap_clamps_jalapeno_pizza_hallucination() -> None:
    """Regression (gs-dinner-0003): LLM assigns 120g of jalapeño slices on a
    pizza topping — implausible for a garnish. 30g ceiling clamps this."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("jalapeño en rodajas (encurtido)", 72, grams=120.0, role="garnish")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 30.0
    # 72 * (30/120) = 18.0
    assert out.kcal == 18


def test_cap_pechuga_also_clamped() -> None:
    """'pechuga' (boneless breast) shares the 200g ceiling with 'pollo'."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("pechuga de pollo a la plancha", 500, grams=300.0, role="main")
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 200.0
    assert out.kcal == 333  # 500 * (200/300) = 333.3 → 333


# ---------------------------------------------------------------------------
# Protein floor (2026-07-25) — lift under-estimated protein mains
# ---------------------------------------------------------------------------

def test_floor_protein_lifts_underestimated_chicken() -> None:
    """LLM reports 30 g chicken breast for a main → lifted to 70 g floor."""
    from app.vision.domain.plate_decomposition import floor_staple_portions

    it = _item("pollo asado", 52, grams=30.0, role="main")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 70.0
    assert out.kcal == round(52 * (70 / 30))


def test_floor_protein_leaves_normal_chicken_untouched() -> None:
    """A realistic 160 g chicken breast is above the 70 g floor → untouched."""
    from app.vision.domain.plate_decomposition import floor_staple_portions

    it = _item("pollo asado", 280, grams=160.0, role="main")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 160.0
    assert out.kcal == 280


def test_floor_protein_lifts_underestimated_salmon() -> None:
    """LLM reports 40 g salmon fillet → lifted to 80 g floor."""
    from app.vision.domain.plate_decomposition import floor_staple_portions

    it = _item("salmón a la plancha", 57, grams=40.0, role="main")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 80.0
    assert out.kcal == round(57 * (80 / 40))


def test_floor_protein_does_not_apply_to_garnish() -> None:
    """Protein floor only fires for role=main/side, never garnish."""
    from app.vision.domain.plate_decomposition import floor_staple_portions

    it = _item("pollo desmenuzado", 25, grams=20.0, role="garnish")
    out = floor_staple_portions([it])[0]
    assert float(out.estimated_amount_g) == 20.0  # untouched


# ---------------------------------------------------------------------------
# Tightened group ceilings (2026-07-25)
# ---------------------------------------------------------------------------

def test_cap_fruit_group_ceiling_tightened() -> None:
    """Fruit ceiling is now 250 g (was 500). A 400 g 'fruta mixta' clamps."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = DetectedFoodItem(
        name="fruta mixta",
        estimated_amount_g=Decimal("400"),
        kcal=208,
        protein_g=2, carbs_g=52, fat_g=1,
        confidence=0.8,
        food_group="fruit", role="side",
        prep_method=None, kcal_min=None, kcal_max=None,
    )
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 250.0
    assert out.kcal == round(208 * 250 / 400)


def test_cap_protein_group_ceiling_tightened() -> None:
    """Protein group ceiling is now 300 g (was 500). A generic 450 g protein clamps."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = DetectedFoodItem(
        name="carne mixta desconocida",
        estimated_amount_g=Decimal("450"),
        kcal=900,
        protein_g=90, carbs_g=0, fat_g=40,
        confidence=0.7,
        food_group="protein", role="main",
        prep_method=None, kcal_min=None, kcal_max=None,
    )
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 300.0
    assert out.kcal == round(900 * 300 / 450)


# --- clamp_meal_total_kcal ---------------------------------------------------


def test_clamp_meal_total_kcal_no_slot_no_change() -> None:
    """Without a slot, totals are never modified."""
    items = [_item("nueces", 400, grams=60), _item("manzana", 200, grams=180)]
    out = clamp_meal_total_kcal(items, slot=None)
    assert sum(i.kcal for i in out) == 600


def test_clamp_meal_total_kcal_snack_over_ceiling() -> None:
    """Snack total 585 kcal (gs-snack-0004 pattern) must scale to SLOT_KCAL_MAX['snack']."""
    items = [
        _item("nueces", 390, grams=60, role="main"),
        _item("manzana", 100, grams=180, role="side"),
        _item("queso", 95, grams=30, role="side"),
    ]
    total_before = sum(i.kcal for i in items)  # 585
    assert total_before == 585
    out = clamp_meal_total_kcal(items, slot="snack")
    total_after = sum(i.kcal for i in out)
    # Integer rounding can leave total 1-2 kcal below ceiling — check it's ≤ ceiling
    assert total_after <= SLOT_KCAL_MAX["snack"]
    assert total_after >= SLOT_KCAL_MAX["snack"] - 2  # rounding never loses more than 2
    # Proportions preserved: each item scaled by same factor
    factor = SLOT_KCAL_MAX["snack"] / 585
    assert out[0].kcal == int(round(390 * factor))
    assert out[1].kcal == int(round(100 * factor))
    assert out[2].kcal == int(round(95 * factor))


def test_clamp_meal_total_kcal_snack_below_ceiling_unchanged() -> None:
    """Snack total under the ceiling must pass through unchanged."""
    items = [_item("yogur", 90, grams=150), _item("arandanos", 40, grams=70)]
    out = clamp_meal_total_kcal(items, slot="snack")
    assert out[0].kcal == 90
    assert out[1].kcal == 40


def test_clamp_meal_total_kcal_scales_grams_proportionally() -> None:
    """Grams must scale by the same factor as kcal so density is preserved."""
    items = [_item("nueces", 650, grams=100, role="main")]
    out = clamp_meal_total_kcal(items, slot="snack")
    factor = SLOT_KCAL_MAX["snack"] / 650
    assert abs(float(out[0].estimated_amount_g) - round(100 * factor, 1)) < 0.2


def test_clamp_meal_total_kcal_unknown_slot_no_change() -> None:
    """Unknown slot string (e.g. 'brunch') must not change anything."""
    items = [_item("huevo", 300, grams=200)]
    out = clamp_meal_total_kcal(items, slot="brunch")
    assert out[0].kcal == 300


def test_clamp_meal_total_kcal_snack_within_25pct_of_gs_snack_0004_gt() -> None:
    """After clamping 585-kcal snack, result must be within ±25% of GT=220 kcal."""
    items = [
        _item("nueces", 390, grams=60),
        _item("manzana", 100, grams=180),
        _item("queso", 95, grams=30),
    ]
    out = clamp_meal_total_kcal(items, slot="snack")
    total = sum(i.kcal for i in out)
    gt = 220
    delta_pct = abs(total - gt) / gt
    assert delta_pct <= 0.25, f"Total {total} not within 25% of GT {gt} ({delta_pct:.1%})"


def test_clamp_meal_total_kcal_preserves_kcal_min_max() -> None:
    """kcal_min/kcal_max are scaled proportionally when set."""
    items = [_item("nueces", 650, grams=100, role="main", kcal_min=550, kcal_max=750)]
    out = clamp_meal_total_kcal(items, slot="snack")
    factor = SLOT_KCAL_MAX["snack"] / 650
    assert out[0].kcal_min == int(round(550 * factor))
    assert out[0].kcal_max == int(round(750 * factor))


def test_clamp_meal_total_kcal_empty_list() -> None:
    out = clamp_meal_total_kcal([], slot="snack")
    assert out == []


def test_clamp_meal_total_kcal_integrated_in_decompose() -> None:
    """decompose() with slot='snack' must apply the total kcal guard."""
    items = [
        _item("nueces", 390, grams=60, role="main"),
        _item("manzana", 100, grams=180, role="side"),
        _item("queso", 95, grams=30, role="side"),
    ]
    result_items, totals = decompose(items, slot="snack")
    # After decompose, total must not exceed snack ceiling
    assert totals.kcal <= SLOT_KCAL_MAX["snack"], (
        f"decompose total {totals.kcal} exceeds snack ceiling {SLOT_KCAL_MAX['snack']}"
    )
