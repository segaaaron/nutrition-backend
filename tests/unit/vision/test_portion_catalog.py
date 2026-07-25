"""Unit tests for portion_catalog.resolve_grams()."""
from __future__ import annotations

import pytest

from app.vision.domain.portion_catalog import PORTION_GRAMS, resolve_grams


class TestResolveGramsBasic:
    def test_unknown_size_category_returns_zero(self) -> None:
        assert resolve_grams("arroz", "grain", "HUGE") == 0
        assert resolve_grams("arroz", "grain", "") == 0
        assert resolve_grams("arroz", "grain", "medium") == 0  # must be uppercase XS/S/M/L/XL

    def test_size_category_case_insensitive(self) -> None:
        assert resolve_grams("arroz", "grain", "m") == resolve_grams("arroz", "grain", "M")
        assert resolve_grams("arroz", "grain", "xs") == resolve_grams("arroz", "grain", "XS")

    def test_sizes_are_strictly_increasing(self) -> None:
        for name, food_group in [
            ("pollo a la plancha", "protein"),
            ("arroz blanco", "grain"),
            ("salmón al horno", "protein"),
            ("papas fritas", "grain"),
        ]:
            sizes = [resolve_grams(name, food_group, cat) for cat in ("XS", "S", "M", "L", "XL")]
            for a, b in zip(sizes, sizes[1:]):
                assert a < b, f"{name}: sizes not strictly increasing: {sizes}"

    def test_all_sizes_positive(self) -> None:
        for cat in ("XS", "S", "M", "L", "XL"):
            assert resolve_grams("pollo", "protein", cat) > 0


class TestFoodTypeResolution:
    """Verify known food names map to correct type and reasonable grams."""

    @pytest.mark.parametrize("name, food_group, size, expected_range", [
        # Poultry — M normal home serving
        ("pechuga de pollo", "protein", "M", (110, 150)),
        ("chicken breast", "protein", "M", (110, 150)),
        ("muslo de pollo", "protein", "M", (110, 150)),
        # Fish — M normal serving
        ("salmón al horno", "protein", "M", (120, 160)),
        ("filete de pescado", "protein", "M", (120, 160)),
        ("bacalao", "protein", "M", (120, 160)),
        # Red meat
        ("lomo de res", "protein", "M", (130, 170)),
        ("bistec de cerdo", "protein", "M", (130, 170)),
        # Egg — M = 1 large egg
        ("huevo frito", "protein", "M", (55, 70)),
        ("egg scrambled", "protein", "M", (55, 70)),
        # Rice — M normal side
        ("arroz blanco cocido", "grain", "M", (130, 170)),
        ("rice", "grain", "M", (130, 170)),
        # Pasta — M
        ("espagueti con salsa", "grain", "M", (160, 200)),
        ("pasta integral", "grain", "M", (160, 200)),
        # Potato
        ("papa cocida", "grain", "M", (130, 170)),
        ("puré de papas", "grain", "M", (130, 170)),
        # Fries — M moderate side
        ("papas fritas", "grain", "M", (110, 150)),
        # Legumes
        ("frijoles negros", "protein", "M", (100, 140)),
        ("lenteja cocida", "protein", "M", (100, 140)),
        # Salad
        ("ensalada mixta", "vegetable", "M", (80, 120)),
        # Vegetable cooked
        ("brócoli al vapor", "vegetable", "M", (85, 115)),
        # Fruit
        ("mango en trozos", "fruit", "M", (130, 170)),
        # Yogurt
        ("yogur natural", "dairy", "M", (160, 200)),
        # Soup
        ("sopa de pollo", "other", "M", (270, 330)),
        # Smoothie
        ("batido de fresa", "beverage", "M", (270, 330)),
        # Sauce
        ("salsa de tomate", "other", "M", (20, 30)),
        # Fat
        ("aceite de oliva", "fat", "M", (12, 18)),
    ])
    def test_known_food_grams_in_range(
        self, name: str, food_group: str, size: str, expected_range: tuple[int, int]
    ) -> None:
        g = resolve_grams(name, food_group, size)
        lo, hi = expected_range
        assert lo <= g <= hi, f"{name} {size}: got {g}g, expected {lo}-{hi}g"


class TestGroupFallback:
    """When name doesn't match any keyword, food_group is used."""

    def test_unknown_name_uses_food_group_grain(self) -> None:
        g = resolve_grams("platillo desconocido xyz", "grain", "M")
        # grain → rice → M = 150
        assert g == 150

    def test_unknown_name_uses_food_group_protein(self) -> None:
        g = resolve_grams("proteína extraña", "protein", "M")
        assert g > 0

    def test_unknown_name_food_group_fat(self) -> None:
        g = resolve_grams("grasa xyz", "fat", "S")
        assert g == PORTION_GRAMS["fat"][1]  # S index


class TestPortionCatalogTableSanity:
    def test_all_sizes_five_values(self) -> None:
        for key, vals in PORTION_GRAMS.items():
            assert len(vals) == 5, f"{key}: expected 5 sizes, got {len(vals)}"

    def test_all_values_positive(self) -> None:
        for key, vals in PORTION_GRAMS.items():
            for g in vals:
                assert g > 0, f"{key}: zero gram value"

    def test_all_sizes_monotone(self) -> None:
        for key, vals in PORTION_GRAMS.items():
            for a, b in zip(vals, vals[1:]):
                assert a < b, f"{key}: not strictly increasing: {vals}"

    def test_medium_serving_reasonable(self) -> None:
        # M (index 2) must be between 10g and 600g for all food types
        for key, vals in PORTION_GRAMS.items():
            m = vals[2]
            assert 10 <= m <= 600, f"{key} M={m}g outside plausible range"
