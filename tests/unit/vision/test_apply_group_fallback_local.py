"""Unit tests for apply_group_fallback local-USDA path.

Verifies that items matched by local USDA JSON:
  - get match_method = "usda_local"
  - never hit the FDC network API
  - receive correct scaled kcal (USDA per-100g × estimated_amount_g / 100)
  - fall through to FDC when local match is absent
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.macro_grounder import apply_group_fallback


def _item(
    name: str,
    *,
    kcal: int = 0,
    amount_g: float = 150.0,
    food_group: str = "protein",
    inferred: bool = False,
) -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal(str(amount_g)),
        kcal=kcal,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=0.8,
        food_group=food_group,
        inferred=inferred,
        matched_food_id=None,
    )


# ---------------------------------------------------------------------------
# Local match — bypasses FDC
# ---------------------------------------------------------------------------

def test_local_match_bypasses_fdc() -> None:
    """pechuga de pollo → USDA local (120 kcal/100g). FDC must NOT be called."""
    item = _item("pechuga de pollo asada", kcal=0, amount_g=150.0)

    mock_fdc = AsyncMock()
    with patch("app.vision.infrastructure.usda_fdc.search", mock_fdc):
        asyncio.run(apply_group_fallback([item]))

    mock_fdc.assert_not_called()
    assert item.match_method == "usda_local"
    # USDA: 120 kcal/100g × 1.5 = 180 kcal
    assert item.kcal == 180
    assert item.kcal_min == round(180 * 0.80)
    assert item.kcal_max == round(180 * 1.20)


def test_local_match_salmon_scales_correctly() -> None:
    """salmón → 142 kcal/100g. At 200g → 284 kcal."""
    item = _item("filete de salmón", kcal=0, amount_g=200.0)

    with patch("app.vision.infrastructure.usda_fdc.search", AsyncMock()):
        asyncio.run(apply_group_fallback([item]))

    assert item.match_method == "usda_local"
    assert item.kcal == 284  # 142 × 2.0
    assert item.protein_g > 0  # protein set from USDA


def test_local_match_sets_fiber_and_sugar() -> None:
    """Fiber/sugar fields populated from local USDA (not left at 0)."""
    item = _item("frijol negro", kcal=0, amount_g=100.0, food_group="protein")

    with patch("app.vision.infrastructure.usda_fdc.search", AsyncMock()):
        asyncio.run(apply_group_fallback([item]))

    assert item.match_method == "usda_local"
    # frijol negro cocido: fiber_g > 0 in USDA reference
    assert item.fiber_g > 0


# ---------------------------------------------------------------------------
# Local match rejected by 5× sanity band → falls through to FDC
# ---------------------------------------------------------------------------

def test_local_match_rejected_falls_to_fdc() -> None:
    """If LLM kcal is wildly above local estimate, local is rejected → FDC called.

    Note: FDC also gives ~180 kcal for pechuga (same USDA data), so it too
    fails the 5× sanity band when LLM=2000. The assertion is therefore that
    FDC IS called (fall-through works) — not that FDC sets match_method, since
    both sources disagree with the absurd LLM estimate and both are rejected.
    """
    # pechuga 150g → local = 180 kcal. LLM=2000 → 2000/5=400 > 180 → local rejected.
    item = _item("pechuga de pollo asada", kcal=2000, amount_g=150.0)

    fdc_result = MagicMock()
    fdc_result.kcal_per_100g = 120.0
    fdc_result.protein_per_100g = 22.0
    fdc_result.carbs_per_100g = 0.0
    fdc_result.fat_per_100g = 2.5
    fdc_result.fiber_per_100g = 0.0
    fdc_result.sugar_per_100g = 0.0

    mock_fdc = AsyncMock(return_value=fdc_result)
    with patch("app.vision.infrastructure.usda_fdc.search", mock_fdc):
        asyncio.run(apply_group_fallback([item]))

    # FDC must be called — local rejection triggered the fall-through
    mock_fdc.assert_called_once()
    # Both local (180) and FDC (180) fail the 5× band against LLM=2000,
    # so match_method stays None and LLM kcal is preserved.
    assert item.match_method is None
    assert item.kcal == 2000  # LLM value preserved when all sources rejected


# ---------------------------------------------------------------------------
# Inferred items are skipped entirely
# ---------------------------------------------------------------------------

def test_inferred_items_skipped() -> None:
    """Items with inferred=True (cooking fat injections) never enter grounding."""
    item = _item("aceite de cocción", kcal=90, amount_g=10.0, inferred=True)

    mock_fdc = AsyncMock()
    with patch("app.vision.infrastructure.usda_fdc.search", mock_fdc):
        asyncio.run(apply_group_fallback([item]))

    mock_fdc.assert_not_called()
    assert item.match_method is None  # untouched


# ---------------------------------------------------------------------------
# Unknown food → goes to FDC (no local match)
# ---------------------------------------------------------------------------

def test_unknown_food_hits_fdc() -> None:
    """A food not in the 73-item local index must go straight to FDC."""
    item = _item("pizza margherita", kcal=400, amount_g=200.0, food_group="grain")

    fdc_result = MagicMock()
    fdc_result.kcal_per_100g = 250.0
    fdc_result.protein_per_100g = 10.0
    fdc_result.carbs_per_100g = 30.0
    fdc_result.fat_per_100g = 10.0
    fdc_result.fiber_per_100g = 2.0
    fdc_result.sugar_per_100g = 3.0

    mock_fdc = AsyncMock(return_value=fdc_result)
    with patch("app.vision.infrastructure.usda_fdc.search", mock_fdc):
        asyncio.run(apply_group_fallback([item]))

    mock_fdc.assert_called_once()
    assert item.match_method == "usda_fdc"
