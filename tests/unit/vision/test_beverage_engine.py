"""Beverage engine invariants (Fase 1, 2026-06-11).

Drinks are exact-by-construction: standard containers + curated per-100ml
table + the ethanol formula (7 kcal/g × 0.789 g/ml). These tests pin the
physics and the override semantics.
"""

from __future__ import annotations

from decimal import Decimal

from app.vision.domain.beverage_engine import (
    alcohol_kcal,
    match_profile,
    refine_beverages,
    snap_to_container,
)
from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.plate_decomposition import decompose


def _bev(name: str, ml: float, kcal: int, *, group: str = "beverage") -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal(str(ml)),
        kcal=kcal,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=0.8,
        food_group=group,  # type: ignore[arg-type]
    )


# --- physics ------------------------------------------------------------------


def test_alcohol_formula_beer_can() -> None:
    # 355 ml at 5% ABV → 355×0.05×0.789×7 ≈ 98 kcal of ethanol.
    assert round(alcohol_kcal(5.0, 355.0)) == 98


def test_alcohol_formula_pisco_shot() -> None:
    # 44 ml shot at 42% → ≈ 102 kcal. A shot of pisco ~= a beer's alcohol.
    assert 95 <= alcohol_kcal(42.0, 44.0) <= 110


# --- container snapping ---------------------------------------------------------


def test_estimated_350ml_snaps_to_355_can() -> None:
    assert snap_to_container(350.0) == 355.0


def test_estimated_340ml_snaps_to_nearest_standard_can() -> None:
    # 340 is ambiguous between the 330 and 355 cans; nearest wins.
    assert snap_to_container(340.0) == 330.0


def test_estimated_600ml_snaps_to_620_peruvian_bottle() -> None:
    assert snap_to_container(600.0) == 620.0


def test_far_from_any_standard_keeps_estimate() -> None:
    # 850 ml is >12% away from both 750 and 1000 → keep the estimate.
    assert snap_to_container(850.0) == 850.0


# --- profile matching -----------------------------------------------------------


def test_zero_variant_matches_before_brand() -> None:
    p = match_profile("Coca-Cola Zero lata")
    assert p is not None and p.kcal_per_100ml < 1.0


def test_brand_and_accents() -> None:
    p = match_profile("Cusqueña dorada botella")
    assert p is not None and p.abv_pct == 5.0


def test_toronja_is_juice_not_rum() -> None:
    # QA 2026-06-12 regression: substring matching read RON inside
    # "toRONja" → 552 kcal of alcohol on a grapefruit juice.
    p = match_profile("jugo de toronja")
    assert p is not None
    assert p.abv_pct == 0.0
    assert p.kcal_per_100ml < 60


def test_chocolate_caliente_is_not_tea() -> None:
    # QA regression: "chocolaTE calienTE" matched the "te" key → ~1 kcal.
    p = match_profile("chocolate caliente")
    assert p is not None and p.kcal_per_100ml >= 60


def test_licuado_and_batido_do_not_match_tea() -> None:
    assert match_profile("licuado de aguacate") is None or (
        match_profile("licuado de aguacate").kcal_per_100ml > 5  # type: ignore[union-attr]
    )
    assert match_profile("batido de camote") is None or (
        match_profile("batido de camote").kcal_per_100ml > 5  # type: ignore[union-attr]
    )


def test_english_aliases_match_for_us_locale() -> None:
    # Locale=en → the LLM names items in English; both languages must hit.
    cases = {
        "orange juice": 45.0,
        "whole milk": 61.0,
        "hot chocolate": 80.0,
        "red wine": 85.0,
        "black coffee": 1.0,
        "water": 0.0,
    }
    for name, kcal100 in cases.items():
        p = match_profile(name)
        assert p is not None, f"{name} should match"
        assert p.kcal_per_100ml == kcal100, name


def test_english_tea_does_not_fire_inside_other_words() -> None:
    # "tea" token only — never inside "steak" (no beverage match at all).
    p = match_profile("grilled steak")
    assert p is None


def test_mate_is_tea_like() -> None:
    p = match_profile("mate caliente")
    assert p is not None and p.kcal_per_100ml <= 2


def test_sin_azucar_multiword_wins() -> None:
    p = match_profile("coca cola sin azucar")
    assert p is not None and p.kcal_per_100ml < 1.0


def test_milk_keeps_protein_and_fat() -> None:
    # QA regression: refine zeroed protein/fat on dairy → corrupted
    # daily protein tracking.
    out = refine_beverages([_bev("leche entera", 250, 999)])
    milk = out[0]
    assert 150 <= milk.kcal <= 155
    assert milk.protein_g >= 7
    assert milk.fat_g >= 7


def test_zero_ml_beverage_keeps_llm_values() -> None:
    out = refine_beverages([_bev("cerveza", 0, 120)])
    assert out[0].kcal == 120


# --- refinement semantics --------------------------------------------------------


def test_beer_355_overrides_llm_guess() -> None:
    # LLM guessed 250 kcal for a standard can; engine computes ~150-160.
    out = refine_beverages([_bev("cerveza pilsen lata", 355, 250)])
    beer = out[0]
    assert 140 <= beer.kcal <= 165
    assert float(beer.estimated_amount_g) == 355.0
    assert beer.kcal_min is not None and beer.kcal_max is not None
    assert beer.kcal_min <= beer.kcal <= beer.kcal_max


def test_coca_zero_is_near_zero_even_if_llm_said_140() -> None:
    out = refine_beverages([_bev("coca cola zero", 355, 140)])
    assert out[0].kcal <= 2


def test_spirit_uses_formula_only() -> None:
    out = refine_beverages([_bev("pisco", 44, 250)])
    assert 95 <= out[0].kcal <= 110


def test_non_beverage_untouched() -> None:
    plate = _bev("arroz con pollo", 350, 480, group="grain")
    out = refine_beverages([plate])
    assert out[0].kcal == 480


def test_unknown_beverage_keeps_llm_estimate() -> None:
    out = refine_beverages([_bev("kombucha artesanal de la abuela", 300, 90)])
    assert out[0].kcal == 90


def test_decompose_pipeline_includes_beverages() -> None:
    items = [
        _bev("ceviche", 300, 280, group="protein"),
        _bev("inca kola", 350, 220),  # snaps to 355, table → ~149
    ]
    out, totals = decompose(items)
    inca = next(i for i in out if "inca" in i.name)
    assert float(inca.estimated_amount_g) == 355.0
    assert 140 <= inca.kcal <= 155
    assert totals.kcal == sum(i.kcal for i in out)
    assert totals.kcal_min <= totals.kcal <= totals.kcal_max
