"""Domain tests — recipes.diet_classifier (safety-critical, pure).

The guarded failure is serving an animal dish to a vegan. Per the module's
safety design, animal lexicons are intentionally broad: an UNDETECTED animal
term is the dangerous case. These tests lock that behavior and prove the
vegan-safety invariant. No DB / no I/O — pure functions.

qa-elite, team consolidation 2026-07-09.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.recipes.domain.diet_classifier import (
    classify_contains_meat,
    classify_diet,
)

# ── classify_diet: canonical cases ────────────────────────────────────────────

VEGAN_TEXTS = [
    "arroz con frijoles y aguacate",
    "ensalada de quinoa con tomate y pepino",
    "avena con platano y mani",
    "lentejas guisadas con zanahoria",
    "tofu salteado con brocoli y arroz",
]

VEGETARIAN_NOT_VEGAN_TEXTS = [
    "omelette de espinaca con queso",        # egg + dairy
    "yogur con granola y miel",              # dairy + honey
    "pan con mantequilla y mermelada",       # dairy
    "huevo revuelto con tomate",             # egg
    "arroz con leche",                       # dairy
]

MEAT_TEXTS = [
    "pechuga de pollo a la plancha con arroz",
    "lomo de res con papas",
    "hamburguesa con queso",
    "chorizo con huevo",
    "jamon y tocino",
    "milanesa de pollo",
    "chuleta de cerdo",
]

FISH_SEAFOOD_TEXTS = [
    "ceviche de pescado",
    "atun con ensalada",
    "salmon a la parrilla",
    "camarones al ajillo",
    "arroz con mariscos",
]


@pytest.mark.parametrize("text", VEGAN_TEXTS)
def test_vegan_texts_are_vegan_and_vegetarian(text: str) -> None:
    is_veg, is_vegan = classify_diet(text)
    assert is_veg is True, f"expected vegetarian: {text}"
    assert is_vegan is True, f"expected vegan: {text}"


@pytest.mark.parametrize("text", VEGETARIAN_NOT_VEGAN_TEXTS)
def test_dairy_egg_honey_is_vegetarian_not_vegan(text: str) -> None:
    is_veg, is_vegan = classify_diet(text)
    assert is_veg is True, f"expected vegetarian: {text}"
    assert is_vegan is False, f"dairy/egg/honey must NOT be vegan: {text}"


@pytest.mark.parametrize("text", MEAT_TEXTS)
def test_meat_is_neither_vegetarian_nor_vegan(text: str) -> None:
    is_veg, is_vegan = classify_diet(text)
    assert is_veg is False, f"meat must not be vegetarian: {text}"
    assert is_vegan is False, f"meat must not be vegan: {text}"


@pytest.mark.parametrize("text", FISH_SEAFOOD_TEXTS)
def test_fish_and_seafood_are_not_vegetarian(text: str) -> None:
    is_veg, is_vegan = classify_diet(text)
    assert is_veg is False, f"fish/seafood must not be vegetarian: {text}"
    assert is_vegan is False


# ── Plant-override: dairy-named plant products stay vegan ─────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "leche de almendras con avena",
        "queso vegano con pan integral",
        "helado de coco con frutas",
        "mantequilla de mani con platano",
        "yogur de soya con granola",
        "crema de coco con verduras",
    ],
)
def test_plant_named_dairy_substitutes_stay_vegan(text: str) -> None:
    is_veg, is_vegan = classify_diet(text)
    assert is_veg is True, f"plant substitute must be vegetarian: {text}"
    assert is_vegan is True, f"plant substitute must be vegan: {text}"


# ── Accent / casing normalization ────────────────────────────────────────────

def test_normalization_accent_and_case_insensitive() -> None:
    assert classify_diet("POLLO A LA PLANCHA") == (False, False)
    assert classify_diet("Jamón") == classify_diet("jamon")
    assert classify_diet("Frijóles con arróz") == (True, True)


def test_empty_and_whitespace_default_to_vegan() -> None:
    # No animal marker → defaults to vegetarian + vegan (documented behavior).
    assert classify_diet("") == (True, True)
    assert classify_diet("   ") == (True, True)


# ── Vegan-safety INVARIANT (property-based) ───────────────────────────────────
# The critical guarantee: if ANY animal species/product marker is present,
# the recipe must NOT be classified vegan. False positives (excluding a valid
# vegan dish) are acceptable by design; false negatives are dangerous.

_ANIMAL_MARKERS = [
    "pollo", "res", "cerdo", "pavo", "cordero", "conejo",
    "pescado", "atun", "salmon", "trucha", "tilapia",
    "camaron", "pulpo", "calamar", "cangrejo",
    "queso", "leche", "huevo", "miel", "mantequilla",
    "jamon", "tocino", "chorizo", "milanesa", "hamburguesa",
]


@given(
    marker=st.sampled_from(_ANIMAL_MARKERS),
    filler=st.sampled_from(["con arroz", "y ensalada", "al horno", "guisado", ""]),
)
def test_any_animal_marker_is_never_vegan(marker: str, filler: str) -> None:
    _is_veg, is_vegan = classify_diet(f"{marker} {filler}".strip())
    assert is_vegan is False, f"SAFETY VIOLATION: '{marker} {filler}' classified vegan"


# ── classify_contains_meat: pescatarian filter (land meat only) ───────────────

@pytest.mark.parametrize(
    "text",
    ["pechuga de pollo", "lomo de res", "chuleta de cerdo", "chorizo", "filete de res"],
)
def test_land_meat_contains_meat_true(text: str) -> None:
    assert classify_contains_meat(text) is True


@pytest.mark.parametrize(
    "text",
    ["ceviche de pescado", "atun con arroz", "salmon", "camarones", "arroz con mariscos"],
)
def test_fish_and_seafood_do_not_count_as_meat(text: str) -> None:
    # Pescatarians eat fish/seafood — contains_meat is land-animal only.
    assert classify_contains_meat(text) is False


def test_ambiguous_cut_with_fish_is_not_meat() -> None:
    # "filete" is an ambiguous cut; with fish context it is NOT land meat.
    assert classify_contains_meat("filete de merluza") is False
    assert classify_contains_meat("escalope de salmon") is False


def test_ambiguous_cut_with_land_species_is_meat() -> None:
    assert classify_contains_meat("filete de res") is True


@pytest.mark.parametrize("text", ["arroz con frijoles", "ensalada de quinoa", ""])
def test_plant_texts_contain_no_meat(text: str) -> None:
    assert classify_contains_meat(text) is False


# ── Known conservative limitation (documented, not a bug) ─────────────────────

def test_known_limitation_plant_burger_flagged_nonveg() -> None:
    """DESIGN TRADEOFF: 'hamburguesa'/'milanesa' always trip the meat lexicon,
    so a plant burger is conservatively classified non-vegetarian. This is a
    SAFE false-positive (excludes a valid vegan dish rather than risk serving
    meat to a vegan). Locked here so any change to this behavior is deliberate.
    Product note: docs/product/gaps/ tracks the UX cost (vegans denied valid
    vegan dishes named 'hamburguesa de lentejas').
    """
    assert classify_diet("hamburguesa de lentejas") == (False, False)
    assert classify_contains_meat("hamburguesa de lentejas") is True
