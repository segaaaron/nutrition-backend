"""Dietary-pattern hard-exclude: vegan/vegetarian users never get animal food.

The onboarding form collects ``dietary_pattern`` and promises on-screen "NOVA
excluirá los alimentos que no comes". Before 2026-06-16 Layer 1 ignored it and a
vegan could be served meat. These tests pin:

1. Layer 1 SQL emits the NULL-safe hard-exclude (`IS TRUE`) for vegan/vegetarian.
2. The deterministic classifier that backfills the flags never marks an animal
   dish vegetarian/vegan, and is conservative (the safe direction).
"""

from __future__ import annotations

import inspect

import pytest

from app.plan.application import layer1_eligibility
from app.recipes.domain.diet_classifier import classify_contains_meat, classify_diet


def test_layer1_sql_hard_excludes_vegan_and_vegetarian() -> None:
    src = inspect.getsource(layer1_eligibility)
    # NULL-safe: unclassified recipes (NULL) are excluded for these users.
    assert "r.is_vegan IS TRUE" in src, "Layer 1 must hard-exclude non-vegan for vegan users"
    assert (
        "r.is_vegetarian IS TRUE" in src
    ), "Layer 1 must hard-exclude non-vegetarian for vegetarian users"


@pytest.mark.parametrize(
    ("text", "is_vegetarian", "is_vegan"),
    [
        ("Ensalada de quinua, palta y tomate", True, True),
        ("Sopa de lentejas con verduras", True, True),
        ("Bowl de avena con leche de almendras y frutos rojos", True, True),
        ("Tortilla de maiz con frijoles y palta", True, True),  # corn tortilla is vegan
        ("Pollo a la plancha con arroz integral", False, False),
        ("Lomo saltado de res con papas fritas", False, False),
        ("Ceviche de pescado y camaron", False, False),
        ("Tortilla de huevo con espinaca", True, False),
        ("Yogur griego con miel", True, False),
        ("Queso fresco con tomate", True, False),
        # Adversarial: meat/animal named by CUT or PREPARATION, not the species
        # (QA 2026-06-16 BLOCKER — these were classified vegan before).
        ("Hamburguesa clasica con papas", False, False),
        ("Pechuga a la plancha con ensalada", False, False),
        ("Milanesa de res con pure", False, False),
        ("Filete de salmon con esparragos", False, False),
        ("Ensalada griega con feta y aceitunas", True, False),
        ("Helado de vainilla", True, False),
    ],
)
def test_classifier_marks_animal_dishes(text: str, is_vegetarian: bool, is_vegan: bool) -> None:
    assert classify_diet(text) == (is_vegetarian, is_vegan)


def test_vegan_always_implies_vegetarian() -> None:
    for t in ["arroz con verduras", "ensalada de garbanzos", "fruta picada", "pan con palta"]:
        veg, vegan = classify_diet(t)
        assert not vegan or veg, f"{t!r}: vegan must imply vegetarian"


@pytest.mark.parametrize(
    ("text", "expected_contains_meat"),
    [
        # Land meat → True
        ("Lomo saltado de res con papas", True),
        ("Pollo a la plancha con arroz", True),
        ("Pechuga de pollo con ensalada", True),
        ("Hamburguesa clasica con papas", True),
        ("Milanesa de cerdo con pure", True),
        # Fish/seafood → False (pescatarian can eat these)
        ("Ceviche de pescado con limon", False),
        ("Salmon al horno con espinaca", False),
        ("Camaron salteado con verduras", False),
        ("Filete de merluza con arroz", False),
        # Vegan → False
        ("Ensalada de quinua y palta", False),
        ("Sopa de lentejas con verduras", False),
        # Dairy/egg (not meat) → False
        ("Tortilla de huevo con espinaca", False),
        ("Yogur griego con frutos rojos", False),
    ],
)
def test_classify_contains_meat(text: str, expected_contains_meat: bool) -> None:
    assert classify_contains_meat(text) == expected_contains_meat, (
        f"classify_contains_meat({text!r}) → {classify_contains_meat(text)!r}, "
        f"expected {expected_contains_meat!r}"
    )


def test_layer1_sql_pescatarian_uses_contains_meat_not_is_vegetarian() -> None:
    src = inspect.getsource(layer1_eligibility)
    assert "r.contains_meat IS FALSE" in src, (
        "Layer 1 must use 'contains_meat IS FALSE' for pescatarian "
        "(IS FALSE excludes NULL fail-safe; IS NOT TRUE would include NULL)"
    )
