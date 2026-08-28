"""Unit — ground_macros_from_db confidence-stratified disagreement guard.

Tests the G1 root fix: high-confidence matches (personal/trigram) override LLM
kcal even when they disagree by >2x.  Medium-confidence matches (embedding)
keep the existing 2x guard so a wrong semantic match can't silently corrupt kcal.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.macro_grounder import ground_macros_from_db


def _item(
    *,
    kcal_llm: int,
    amount_g: float = 150.0,
    match_method: str = "trigram",
) -> DetectedFoodItem:
    food_id = uuid4()
    it = DetectedFoodItem(
        name="pechuga de pollo",
        estimated_amount_g=Decimal(str(amount_g)),
        kcal=kcal_llm,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=0.9,
        matched_food_id=food_id,
        match_method=match_method,
    )
    return it


def _mock_session(food_id, *, kcal_per_100g: int = 165) -> AsyncMock:
    """Return a fake AsyncSession that yields one DB row for food_id."""
    row = MagicMock()
    row.__getitem__ = lambda self, i: [str(food_id), kcal_per_100g, 31, 0, 4, 0, 0][i]
    result = MagicMock()
    result.all.return_value = [row]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# High-confidence matches (personal / trigram) — DB always wins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigram_high_conf_overrides_llm_when_disagreement_gt_2x() -> None:
    """trigram match: DB kcal replaces LLM even when they differ by >2x."""
    it = _item(kcal_llm=400, amount_g=150.0, match_method="trigram")
    # DB says 165 kcal/100g → 248 kcal for 150g — far below LLM 400 (ratio 1.6x on
    # the /2 side, but this tests the general stratification path).
    session = _mock_session(it.matched_food_id, kcal_per_100g=100)
    # 100 kcal/100g × 150g = 150 kcal; LLM=400 → ratio 400/150 ≈ 2.7x → guard fires.
    await ground_macros_from_db([it], session=session)
    assert it.kcal == 150, f"Expected DB kcal 150, got {it.kcal}"


@pytest.mark.asyncio
async def test_personal_match_always_overrides_llm() -> None:
    """personal match (user correction): DB always wins, no ratio guard at all."""
    it = _item(kcal_llm=800, amount_g=100.0, match_method="personal")
    # DB: 165 kcal/100g → 165 kcal; LLM=800 → ratio 4.8x → embedding would skip, personal must not.
    session = _mock_session(it.matched_food_id, kcal_per_100g=165)
    await ground_macros_from_db([it], session=session)
    assert it.kcal == 165, f"personal match must override LLM kcal; got {it.kcal}"


# ---------------------------------------------------------------------------
# Medium-confidence match (embedding) — existing 2x guard preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_match_keeps_llm_on_large_disagreement() -> None:
    """embedding match: LLM survives when DB disagrees by >2x (wrong semantic match risk)."""
    it = _item(kcal_llm=400, amount_g=150.0, match_method="embedding")
    # DB: 100 kcal/100g → 150 kcal; 400/150 ≈ 2.7x → guard must fire, LLM kept.
    session = _mock_session(it.matched_food_id, kcal_per_100g=100)
    await ground_macros_from_db([it], session=session)
    assert it.kcal == 400, f"embedding guard must preserve LLM kcal on >2x mismatch; got {it.kcal}"


@pytest.mark.asyncio
async def test_embedding_match_applies_db_within_2x() -> None:
    """embedding match within 2x: DB still replaces LLM (no change from previous behaviour)."""
    it = _item(kcal_llm=300, amount_g=150.0, match_method="embedding")
    # DB: 165 kcal/100g → 248 kcal; 300/248 ≈ 1.2x → within 2x → DB wins.
    session = _mock_session(it.matched_food_id, kcal_per_100g=165)
    await ground_macros_from_db([it], session=session)
    assert it.kcal == 248, f"embedding within 2x must apply DB kcal; got {it.kcal}"


# ---------------------------------------------------------------------------
# kcal_min / kcal_max always set from DB (both paths)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigram_override_sets_kcal_range() -> None:
    """After high-conf override, kcal_min/max are computed from DB kcal."""
    it = _item(kcal_llm=500, amount_g=100.0, match_method="trigram")
    session = _mock_session(it.matched_food_id, kcal_per_100g=165)
    await ground_macros_from_db([it], session=session)
    assert it.kcal == 165
    assert it.kcal_min == round(165 * 0.8)
    assert it.kcal_max == round(165 * 1.2)
