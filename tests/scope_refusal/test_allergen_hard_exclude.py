"""ADR-0001 — Layer 1 MUST never return a recipe whose allergens overlap
the user's allergies. We assert this by inspecting the generated SQL: the
`NOT (... && ...)` clause is mandatory when `allergies` is non-empty.
"""

from __future__ import annotations

import inspect

from app.plan.application import layer1_eligibility


def test_layer1_source_contains_hard_allergen_exclude() -> None:
    src = inspect.getsource(layer1_eligibility)
    assert (
        "NOT (CAST(r.allergens AS text[]) && CAST(:allergies AS text[]))" in src
    ), "Layer 1 must hard-exclude allergens via array overlap negation"


def test_layer1_source_filters_contraindications() -> None:
    src = inspect.getsource(layer1_eligibility)
    assert "NOT (r.contraindicated_conditions && CAST(:conditions AS text[]))" in src


def test_layer1_safety_gates_present() -> None:
    src = inspect.getsource(layer1_eligibility)
    for fragment in ("sugar_g <= 15", "sodium_mg <= 600", "sat_fat_g <= 5", "organ_meat"):
        assert fragment in src, f"missing safety gate: {fragment}"


def test_layer1_treenut_defensive_ingredient_scan_present() -> None:
    """Catalog audit 2026-06-01: 37 recipes contain nuts in ingredients[]
    without tree_nuts in allergens[]. Layer 1 MUST scan recipe_components
    when user has tree_nuts allergy to defend against this catalog gap."""
    src = inspect.getsource(layer1_eligibility)
    for fragment in (
        '"tree_nuts" in allergies',
        "NOT EXISTS",
        "recipe_components",
        "nut_pattern",
        "almond",
        "almendra",
        "walnut",
        "cashew",
        "pistachio",
        "hazelnut",
        "macadamia",
    ):
        assert fragment in src, f"missing tree-nut defense fragment: {fragment}"
