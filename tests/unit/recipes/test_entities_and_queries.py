"""Domain tests — recipes entities + search value objects (pure).

Covers: search-query limit invariants, RecipeComponent SQL-mirror invariant,
and translation fallback (i18n moat: locale hit → translation, miss → English).
No DB / no I/O.

qa-elite, team consolidation 2026-07-09.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.recipes.domain.entities import Food, Recipe, RecipeComponent
from app.recipes.domain.value_objects import FoodSearchQuery, RecipeSearchQuery

# ── Search query limit invariants ─────────────────────────────────────────────

@pytest.mark.parametrize("limit", [1, 20, 100])
def test_recipe_query_accepts_valid_limit(limit: int) -> None:
    assert RecipeSearchQuery(limit=limit).limit == limit


@pytest.mark.parametrize("limit", [0, -1, 101, 1000])
def test_recipe_query_rejects_out_of_range_limit(limit: int) -> None:
    with pytest.raises(ValueError, match=r"limit must be in \[1\.\.100\]"):
        RecipeSearchQuery(limit=limit)


@pytest.mark.parametrize("limit", [0, 101])
def test_food_query_rejects_out_of_range_limit(limit: int) -> None:
    with pytest.raises(ValueError, match=r"limit must be in \[1\.\.100\]"):
        FoodSearchQuery(limit=limit)


def test_recipe_query_defaults_are_empty_not_shared() -> None:
    # frozen + default_factory: two instances must not share list identity.
    a = RecipeSearchQuery()
    b = RecipeSearchQuery()
    assert a.regions == [] and a.allergens_exclude == []
    assert a.regions is not b.regions


# ── RecipeComponent invariant (mirrors SQL CHECK, migration 0001) ─────────────

def test_component_requires_at_least_one_source() -> None:
    with pytest.raises(ValueError, match="requires food_id, sub_recipe_id, or free_text_name"):
        RecipeComponent(
            id=uuid4(), recipe_id=uuid4(), food_id=None, sub_recipe_id=None,
            free_text_name=None, amount_g=Decimal("100"), modifier=None, position=0,
        )


@pytest.mark.parametrize("source", ["food", "sub", "text"])
def test_component_accepts_any_single_source(source: str) -> None:
    comp = RecipeComponent(
        id=uuid4(), recipe_id=uuid4(),
        food_id=uuid4() if source == "food" else None,
        sub_recipe_id=uuid4() if source == "sub" else None,
        free_text_name="arroz" if source == "text" else None,
        amount_g=Decimal("150"), modifier=None, position=1,
    )
    assert comp.position == 1


# ── Translation fallback (i18n moat) ──────────────────────────────────────────

def _recipe(**kw: object) -> Recipe:
    base = dict(
        id=uuid4(), name_en="Grilled chicken with rice",
        name_translations={"es": "Pollo a la plancha con arroz"},
        description_en="High protein lunch",
        description_translations={"es": "Almuerzo alto en proteina"},
        image_url=None, kcal=600, protein_g=55, carbs_g=60, fat_g=15,
        fiber_g=8, sugar_g=4, sodium_mg=400, sat_fat_g=3, tags=[],
        meal_time="lunch", prep_min=20,
        instructions_en=["Cook rice", "Grill chicken"],
        instructions_translations={"es": ["Cocina el arroz", "Asa el pollo"]},
        regions=["latam"], allergens=[], recommended_conditions=[],
        contraindicated_conditions=[], target_goals=["muscle_gain"],
    )
    base.update(kw)
    return Recipe(**base)  # type: ignore[arg-type]


def test_translated_name_hits_locale() -> None:
    assert _recipe().translated_name("es") == "Pollo a la plancha con arroz"


def test_translated_name_falls_back_to_english_on_miss() -> None:
    # Unknown locale → English canonical (never empty).
    assert _recipe().translated_name("pt") == "Grilled chicken with rice"


def test_translated_description_and_instructions_fallback() -> None:
    r = _recipe()
    assert r.translated_description("es") == "Almuerzo alto en proteina"
    assert r.translated_description("fr") == "High protein lunch"
    assert r.translated_instructions("es") == ["Cocina el arroz", "Asa el pollo"]
    assert r.translated_instructions("de") == ["Cook rice", "Grill chicken"]


def test_empty_translation_map_always_yields_english() -> None:
    r = _recipe(name_translations={}, description_translations={}, instructions_translations={})
    assert r.translated_name("es") == "Grilled chicken with rice"
    assert r.translated_description("es") == "High protein lunch"
    assert r.translated_instructions("es") == ["Cook rice", "Grill chicken"]


def test_recipe_defaults_excluded_countries_empty_and_unshared() -> None:
    a, b = _recipe(), _recipe()
    assert a.excluded_countries == []
    assert a.excluded_countries is not b.excluded_countries
    assert a.created_at is None


def test_food_translated_name_fallback() -> None:
    food = Food(
        id=uuid4(), name_en="Cassava", name_norm="cassava",
        name_translations={"es": "Yuca"}, brand=None, country="PE",
        portion_g=Decimal("100"), kcal=Decimal("160"), protein_g=Decimal("1.4"),
        carbs_g=Decimal("38"), fat_g=Decimal("0.3"), fiber_g=Decimal("1.8"),
        sugar_g=Decimal("1.7"), sodium_mg=Decimal("14"), sat_fat_g=Decimal("0.1"),
        micronutrients=None, barcode=None, verified=True, source="usda",
    )
    assert food.translated_name("es") == "Yuca"
    assert food.translated_name("en") == "Cassava"
