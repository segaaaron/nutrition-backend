"""Lock the single ingestion path.

`scripts/recipe_ingest.py` exists because every batch used to carry its own
hardcoded nutrition table, and each one got it wrong differently. The
2026-08-04 fatty-liver batch listed sugar as 0 for oats, yogurt, apple and
banana, so its own validator confirmed all 98 recipes cleared the `sugar <= 8`
gate — against numbers that were fiction.

The structural defence is that a caller CANNOT supply nutrition. These tests
fence that: the draft has no nutrient fields, every number is derived from the
components, and a draft that would put wrong data in the catalog is rejected
rather than corrected.
"""

from __future__ import annotations

import dataclasses

import pytest

from scripts.recipe_ingest import (
    MIN_INSTRUCTION_STEPS,
    IngestError,
    RecipeDraft,
    build_row,
    derive_allergens,
)


def _draft(**overrides) -> RecipeDraft:
    base = RecipeDraft(
        name_en="Grilled chicken with quinoa and broccoli",
        name_es="Pollo a la plancha con quinoa y brócoli",
        description_en="High-protein lunch with quinoa and broccoli.",
        description_es="Almuerzo alto en proteína con quinoa y brócoli.",
        meal_time="lunch",
        components=[
            ("Pechuga de pollo (cruda)", 200),
            ("Quinoa cocida", 150),
            ("Brócoli (crudo)", 120),
            ("Aceite de oliva", 10),
        ],
        source_batch="unit_test",
    )
    return dataclasses.replace(base, **overrides) if overrides else base


# --------------------------------------------------------------------------
# The structural guarantee
# --------------------------------------------------------------------------
def test_draft_exposes_no_nutrient_fields() -> None:
    """The whole point. If a batch can pass `kcal=130`, it eventually will."""
    fields = {f.name for f in dataclasses.fields(RecipeDraft)}
    forbidden = {
        "kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g",
        "added_sugar_g", "sat_fat_g", "sodium_mg", "allergens",
    }
    leaked = fields & forbidden
    assert not leaked, (
        f"RecipeDraft grew nutrient fields {sorted(leaked)}. Nutrition must be "
        "derived from components, never asserted by the caller."
    )


def test_stored_kcal_is_atwater_over_stored_macros() -> None:
    """Satisfies ck_recipes_kcal_atwater by construction, not by luck."""
    row = build_row(_draft())
    assert row["kcal"] == row["protein_g"] * 4 + row["carbs_g"] * 4 + row["fat_g"] * 9


def test_nutrition_is_derived_and_non_zero() -> None:
    row = build_row(_draft())
    for nutrient in ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg"):
        assert row[nutrient] > 0, nutrient
    # Chicken, quinoa, broccoli and olive oil carry no added sugar.
    assert row["added_sugar_g"] == 0
    assert row["added_sugar_g"] <= row["sugar_g"]


def test_safety_columns_round_conservatively() -> None:
    """Integer columns must never make a recipe look safer than it is."""
    row = build_row(_draft(components=[
        ("Pechuga de pollo (cruda)", 200),
        ("Quinoa cocida", 150),
        ("Brócoli (crudo)", 120),
        ("Aceite de oliva", 10),
        ("Sal", 2),   # 2 g of salt is ~775 mg sodium — must not vanish
    ]))
    assert row["sodium_mg"] > 700, "salt's sodium was lost"


# --------------------------------------------------------------------------
# Derivation of the fields batches kept forgetting
# --------------------------------------------------------------------------
def test_instructions_are_derived_when_omitted() -> None:
    """98 recipes shipped with `instructions_en = []`. Never again."""
    row = build_row(_draft())
    assert len(row["instructions_en"]) >= MIN_INSTRUCTION_STEPS
    assert len(row["instructions_es"]) >= MIN_INSTRUCTION_STEPS


def test_target_goals_derived_when_omitted() -> None:
    """24 recipes shipped with an empty array, so Layer 1 could never pick them."""
    row = build_row(_draft())
    assert row["target_goals"]


def test_allergens_derived_from_components() -> None:
    """Layer 1 excludes on `recipes.allergens` and never reads the components,
    so an undeclared peanut is served to a peanut-allergic user."""
    assert "peanuts" in derive_allergens([("Mantequilla de maní", 30)])
    assert "sesame" in derive_allergens([("Hummus comercial", 60)])
    assert derive_allergens([("Pechuga de pollo (cruda)", 200)]) == []


def test_vegetarian_inferred_from_ingredients() -> None:
    row = build_row(_draft())
    assert row["is_vegetarian"] is False, "a chicken dish is not vegetarian"


# --------------------------------------------------------------------------
# Rejection: a bad draft must fail, never be silently corrected
# --------------------------------------------------------------------------
def test_unresolvable_ingredient_is_rejected() -> None:
    """Defaulting an unknown ingredient to zero understates the whole recipe."""
    with pytest.raises(IngestError, match="do not resolve to USDA"):
        build_row(_draft(components=[("unobtainium purée", 100)]))


def test_kcal_outside_slot_band_is_rejected() -> None:
    with pytest.raises(IngestError, match="outside the lunch band"):
        build_row(_draft(components=[("Manzana (cruda con piel)", 100)]))


def test_protein_below_slot_minimum_is_rejected() -> None:
    with pytest.raises(IngestError, match="below the .* minimum"):
        build_row(_draft(
            meal_time="lunch",
            components=[("Arroz blanco cocido", 400), ("Aceite de oliva", 30)],
        ))


def test_vegan_claim_contradicted_by_ingredients_is_rejected() -> None:
    """A wrong TRUE here serves an animal dish to a vegan — unrecoverable."""
    with pytest.raises(IngestError, match="is_vegan=True"):
        build_row(_draft(is_vegan=True))


def test_retired_condition_is_rejected() -> None:
    """REGLA #0.5.C closed the scope to three situations."""
    with pytest.raises(IngestError, match="unsupported conditions"):
        build_row(_draft(recommended_conditions=["diabetes"]))


def test_unsupported_region_is_rejected() -> None:
    with pytest.raises(IngestError, match="unsupported regions"):
        build_row(_draft(regions=["MX"]))


def test_empty_regions_is_rejected() -> None:
    with pytest.raises(IngestError, match="reach no market"):
        build_row(_draft(regions=[]))


def test_blank_description_is_rejected() -> None:
    with pytest.raises(IngestError, match="description_en is empty"):
        build_row(_draft(description_en="   "))


def test_recipe_without_components_is_rejected() -> None:
    with pytest.raises(IngestError, match="untraceable"):
        build_row(_draft(components=[]))


def test_unknown_meal_time_is_rejected() -> None:
    with pytest.raises(IngestError, match="unknown meal_time"):
        build_row(_draft(meal_time="brunch"))
