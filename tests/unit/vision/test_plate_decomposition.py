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
