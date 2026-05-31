"""Sprint 7.C — deterministic categorisation rules."""
from __future__ import annotations

import pytest

from app.grocery.domain import GroceryCategory, categorise


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Apple", GroceryCategory.FRUITS_VEGETABLES),
        ("Banana", GroceryCategory.FRUITS_VEGETABLES),
        ("Spinach leaves", GroceryCategory.FRUITS_VEGETABLES),
        ("Chicken breast", GroceryCategory.PROTEINS),
        ("Salmon fillet", GroceryCategory.PROTEINS),
        ("Egg, large", GroceryCategory.PROTEINS),
        ("Greek yogurt", GroceryCategory.DAIRY),
        ("Whole milk", GroceryCategory.DAIRY),
        ("Brown rice", GroceryCategory.PANTRY),
        ("Olive oil", GroceryCategory.PANTRY),
        ("Mystery ingredient xyz", GroceryCategory.OTHER),
    ],
)
def test_categorise(name, expected):
    assert categorise(name) == expected


def test_categorise_handles_spanish_names():
    assert categorise("Manzana roja") == GroceryCategory.FRUITS_VEGETABLES
    assert categorise("Pollo a la plancha") == GroceryCategory.PROTEINS
