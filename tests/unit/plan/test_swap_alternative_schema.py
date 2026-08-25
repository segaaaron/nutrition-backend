"""Unit — SwapAlternative + SwapMealResponse schemas (C11)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError as PydValidationError

from app.plan.presentation.schemas import SwapAlternative, SwapMealResponse


def test_swap_alternative_full_fields():
    rid = uuid4()
    alt = SwapAlternative(
        recipe_id=rid,
        name_es="Pollo con arroz y brócoli",
        name_en="Chicken with rice and broccoli",
        kcal=550,
        protein_g=40,
        carbs_g=60,
        fat_g=12,
    )
    assert alt.recipe_id == rid
    assert alt.name_es == "Pollo con arroz y brócoli"
    assert alt.kcal == 550
    assert alt.protein_g == 40


def test_swap_alternative_minimal_only_recipe_id():
    rid = uuid4()
    alt = SwapAlternative(recipe_id=rid)
    assert alt.recipe_id == rid
    assert alt.name_es is None
    assert alt.kcal is None


def test_swap_alternative_rejects_extra_fields():
    with pytest.raises(PydValidationError):
        SwapAlternative(recipe_id=uuid4(), unknown_field="x")  # type: ignore[call-arg]


def test_swap_meal_response_detail_len_matches_alternatives():
    rid = uuid4()
    r = SwapMealResponse(
        alternatives=[rid],
        alternatives_detail=[
            SwapAlternative(recipe_id=rid, name_es="Huevo revuelto con espinacas", kcal=320)
        ],
    )
    assert len(r.alternatives) == len(r.alternatives_detail)
    assert r.alternatives_detail[0].recipe_id == rid


def test_swap_meal_response_detail_defaults_empty():
    rid = uuid4()
    r = SwapMealResponse(alternatives=[rid])
    assert r.alternatives_detail == []


def test_swap_meal_response_order_preserved():
    ids = [uuid4() for _ in range(3)]
    alts_detail = [SwapAlternative(recipe_id=rid, kcal=i * 100) for i, rid in enumerate(ids, 1)]
    r = SwapMealResponse(alternatives=ids, alternatives_detail=alts_detail)
    for i, (alt_id, detail) in enumerate(zip(r.alternatives, r.alternatives_detail), 1):
        assert alt_id == detail.recipe_id
        assert detail.kcal == i * 100
