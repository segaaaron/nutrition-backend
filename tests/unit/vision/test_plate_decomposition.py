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
    clamp_dry_spices,
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
    to the GENERIC food_group ceiling — but a normal 350 g portion is well under
    it, so it is left untouched. Proves the generic net does not over-clamp."""
    from app.vision.domain.plate_decomposition import cap_implausible_portions

    it = _item("guiso de res", 600, grams=350.0, role="main")  # group "other" → 600 g
    out = cap_implausible_portions([it])[0]
    assert float(out.estimated_amount_g) == 350.0


def test_cap_generic_group_backstop_catches_unlisted_food() -> None:
    """THE fix for the bun-bug class: an un-whitelisted food (no name marker, no
    small role) is NO LONGER uncapped. A 'main' grain read at 900 g is clamped by
    the generic food_group='grain' ceiling (500 g). Nothing falls through."""
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
    assert float(out.estimated_amount_g) == 500.0  # generic grain ceiling
    assert out.kcal == 1000  # 1800 * (500/900)


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
