"""Unit — G2: is_mixed_dish flag propagation and kcal range widening.

Verifies:
- _parse_items reads is_mixed_dish from top-level raw dict and sets it on
  every DetectedFoodItem in the response.
- _parse_identifications reads is_mixed_dish and sets it on every
  FoodIdentification.
- _should_fallback escalates with reason "mixed_dish" when any item has
  is_mixed_dish=True.
- _kcal_range returns ±30% for mixed dishes, ±20% for clean plates.
- ground_macros_from_db uses wide range when is_mixed_dish=True.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.macro_grounder import _kcal_range, ground_macros_from_db
from app.vision.infrastructure.openai_vision import (
    _parse_identifications,
    _parse_items,
    _should_fallback,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ITEM_RAW = {
    "name": "arroz con pollo",
    "portion_kind": "a_granel",
    "count": 1,
    "size_category": "M",
    "estimated_amount_g": 250,
    "kcal": 400,
    "protein_g": 25,
    "carbs_g": 45,
    "fat_g": 10,
    "confidence": 0.8,
    "food_group": "protein",
    "role": "main",
    "prep_method": "stewed",
    "bbox": None,
}

_IDENTIFY_RAW = {
    "name": "arroz con pollo",
    "confidence": 0.8,
    "group": "protein",
    "role": "main",
    "prep_method": "stewed",
    "count": 1,
    "portion_kind": "a_granel",
}


def _detected_item(*, kcal: int = 400, is_mixed_dish: bool = False) -> DetectedFoodItem:
    food_id = uuid4()
    return DetectedFoodItem(
        name="arroz con pollo",
        estimated_amount_g=Decimal("250"),
        kcal=kcal,
        protein_g=25,
        carbs_g=45,
        fat_g=10,
        confidence=0.8,
        matched_food_id=food_id,
        match_method="trigram",
        is_mixed_dish=is_mixed_dish,
    )


def _mock_session(food_id, *, kcal_per_100g: int = 200) -> AsyncMock:
    row = MagicMock()
    row.__getitem__ = lambda self, i: [str(food_id), kcal_per_100g, 10, 35, 8, 2, 0][i]
    result = MagicMock()
    result.all.return_value = [row]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# _parse_items — is_mixed_dish propagation
# ---------------------------------------------------------------------------

def test_parse_items_sets_is_mixed_dish_true() -> None:
    raw = {"is_mixed_dish": True, "unit_census": "", "items": [_ITEM_RAW]}
    items = _parse_items(raw)
    assert len(items) == 1
    assert items[0].is_mixed_dish is True


def test_parse_items_sets_is_mixed_dish_false() -> None:
    raw = {"is_mixed_dish": False, "unit_census": "", "items": [_ITEM_RAW]}
    items = _parse_items(raw)
    assert items[0].is_mixed_dish is False


def test_parse_items_missing_key_defaults_false() -> None:
    raw = {"unit_census": "", "items": [_ITEM_RAW]}
    items = _parse_items(raw)
    assert items[0].is_mixed_dish is False


def test_parse_items_propagates_to_all_items() -> None:
    raw = {"is_mixed_dish": True, "unit_census": "", "items": [_ITEM_RAW, _ITEM_RAW]}
    items = _parse_items(raw)
    assert all(it.is_mixed_dish for it in items)


# ---------------------------------------------------------------------------
# _parse_identifications — is_mixed_dish propagation
# ---------------------------------------------------------------------------

def test_parse_identifications_sets_is_mixed_dish_true() -> None:
    raw = {"is_mixed_dish": True, "items": [_IDENTIFY_RAW]}
    ids = _parse_identifications(raw)
    assert len(ids) == 1
    assert ids[0].is_mixed_dish is True


def test_parse_identifications_defaults_false() -> None:
    raw = {"items": [_IDENTIFY_RAW]}
    ids = _parse_identifications(raw)
    assert ids[0].is_mixed_dish is False


# ---------------------------------------------------------------------------
# _should_fallback — mixed_dish escalation
# ---------------------------------------------------------------------------

def test_should_fallback_escalates_on_mixed_dish() -> None:
    item = _detected_item(is_mixed_dish=True)
    escalate, reason = _should_fallback([item], threshold=0.75)
    assert escalate is True
    assert reason == "mixed_dish"


def test_should_fallback_no_escalation_clean_plate() -> None:
    item = _detected_item(is_mixed_dish=False)
    # confidence 0.8 > any typical threshold
    escalate, reason = _should_fallback([item], threshold=0.5)
    assert escalate is False
    assert reason == ""


# ---------------------------------------------------------------------------
# _kcal_range helper
# ---------------------------------------------------------------------------

def test_kcal_range_clean_plate_20_pct() -> None:
    lo, hi = _kcal_range(200, is_mixed_dish=False)
    assert lo == 160  # 200 * 0.80
    assert hi == 240  # 200 * 1.20


def test_kcal_range_mixed_dish_30_pct() -> None:
    lo, hi = _kcal_range(200, is_mixed_dish=True)
    assert lo == 140  # 200 * 0.70
    assert hi == 260  # 200 * 1.30


# ---------------------------------------------------------------------------
# ground_macros_from_db — range widens for mixed dishes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ground_macros_uses_wide_range_for_mixed_dish() -> None:
    it = _detected_item(kcal=400, is_mixed_dish=True)
    # DB: 200 kcal/100g × 250g = 500 kcal (within 2× of 400 → applies)
    session = _mock_session(it.matched_food_id, kcal_per_100g=200)
    await ground_macros_from_db([it], session=session)
    kcal_db = 500
    assert it.kcal_min == round(kcal_db * 0.70)
    assert it.kcal_max == round(kcal_db * 1.30)


@pytest.mark.asyncio
async def test_ground_macros_uses_normal_range_for_clean_plate() -> None:
    it = _detected_item(kcal=400, is_mixed_dish=False)
    session = _mock_session(it.matched_food_id, kcal_per_100g=200)
    await ground_macros_from_db([it], session=session)
    kcal_db = 500
    assert it.kcal_min == round(kcal_db * 0.80)
    assert it.kcal_max == round(kcal_db * 1.20)
