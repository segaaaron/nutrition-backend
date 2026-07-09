"""Unit — HybridFoodMatcher resolution precedence.

Precedence:
  1. personal corrections (vision_user_corrections) — returns corrected_amount_g
  2. trigram on foods.name_norm (sim >= 0.45)
  3. pgvector cosine fallback (dist <= 0.30)
  4. unmatched

Each tier short-circuits the next. The SQL session is mocked at the
boundary; the embedder is mocked because it's external I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.infrastructure.food_matcher import (
    HybridFoodMatcher,
    _normalise,
)


def _stub_session(rows: list):
    """Each .execute(...) consumes one row from `rows`. row=None → no match."""
    session = MagicMock()
    iterator = iter(rows)

    async def _exec(*_args, **_kwargs):
        row = next(iterator, None)
        result = MagicMock()
        result.first = MagicMock(return_value=row)
        return result

    session.execute = AsyncMock(side_effect=_exec)
    return session


def test_normalise_strips_accents_and_punctuation():
    assert _normalise("Plátano!") == "platano"


def test_normalise_collapses_whitespace_and_lowercases():
    assert _normalise("  Arroz   BLANCO  ") == "arroz blanco"


@pytest.mark.asyncio
async def test_empty_name_returns_unmatched_without_db():
    session = MagicMock()
    session.execute = AsyncMock()
    matcher = HybridFoodMatcher(session=session, embedder=MagicMock())

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="!!",
        amount_g=100,
        locale="es",
        user_id=uuid4(),
    )

    assert (food_id, name_norm, method, corrected_g) == (None, None, "unmatched", None)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_correction_hit_short_circuits():
    food_uuid = uuid4()
    # personal row: (corrected_food_id, corrected_amount_g)
    session = _stub_session([(str(food_uuid), None)])
    matcher = HybridFoodMatcher(session=session, embedder=MagicMock())

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="arroz",
        amount_g=100,
        locale="es",
        user_id=uuid4(),
    )

    assert food_id == food_uuid
    assert method == "personal"
    assert corrected_g is None
    # Only one query (personal correction) — no trigram or embedding fired.
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_personal_correction_returns_corrected_amount():
    food_uuid = uuid4()
    session = _stub_session([(str(food_uuid), 175.0)])
    matcher = HybridFoodMatcher(session=session, embedder=MagicMock())

    food_id, _, method, corrected_g = await matcher.match(
        name="pollo",
        amount_g=120,
        locale="es",
        user_id=uuid4(),
    )

    assert food_id == food_uuid
    assert method == "personal"
    assert corrected_g == 175.0


@pytest.mark.asyncio
async def test_no_personal_lookup_when_user_id_is_none():
    food_uuid = uuid4()
    # First call (personal) is SKIPPED → trigram result first.
    session = _stub_session([(str(food_uuid), "arroz blanco", 0.9)])
    matcher = HybridFoodMatcher(session=session, embedder=MagicMock())

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="Arroz",
        amount_g=100,
        locale="es",
        user_id=None,
    )

    assert food_id == food_uuid
    assert method == "trigram"
    assert corrected_g is None
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_trigram_hit_above_threshold():
    food_uuid = uuid4()
    # personal row=None, then trigram row with sim 0.6
    session = _stub_session(
        [
            None,  # no personal correction
            (str(food_uuid), "manzana roja", 0.6),
        ]
    )
    matcher = HybridFoodMatcher(session=session, embedder=MagicMock())

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="manzana",
        amount_g=80,
        locale="es",
        user_id=uuid4(),
    )

    assert food_id == food_uuid
    assert method == "trigram"
    assert corrected_g is None


@pytest.mark.asyncio
async def test_trigram_below_threshold_falls_through_to_embedding():
    fallback_uuid = uuid4()
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    session = _stub_session(
        [
            None,  # no personal correction
            (str(uuid4()), "x", 0.2),  # trigram below 0.45 threshold
            (str(fallback_uuid), "pera verde", 0.15),  # embedding hit dist=0.15
        ]
    )
    matcher = HybridFoodMatcher(session=session, embedder=embedder)

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="pear",
        amount_g=120,
        locale="en",
        user_id=uuid4(),
    )

    assert food_id == fallback_uuid
    assert method == "embedding"
    assert corrected_g is None


@pytest.mark.asyncio
async def test_embedding_skipped_on_embedder_error_returns_unmatched():
    embedder = MagicMock()
    embedder.embed = AsyncMock(side_effect=RuntimeError("openai down"))
    session = _stub_session(
        [
            None,  # no personal correction
            None,  # no trigram hit
        ]
    )
    matcher = HybridFoodMatcher(session=session, embedder=embedder)

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="quinoa",
        amount_g=80,
        locale="en",
        user_id=uuid4(),
    )

    assert (food_id, method, corrected_g) == (None, "unmatched", None)


@pytest.mark.asyncio
async def test_embedding_above_distance_threshold_returns_unmatched():
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[0.5] * 3)
    session = _stub_session(
        [
            None,  # personal
            None,  # trigram
            (str(uuid4()), "anchoa", 0.85),  # embedding dist 0.85 > 0.30
        ]
    )
    matcher = HybridFoodMatcher(session=session, embedder=embedder)

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="batatas fritas",
        amount_g=100,
        locale="es",
        user_id=uuid4(),
    )

    assert (food_id, method, corrected_g) == (None, "unmatched", None)
    assert name_norm == "batatas fritas"


@pytest.mark.asyncio
async def test_personal_row_with_null_food_id_falls_through():
    food_uuid = uuid4()
    session = _stub_session(
        [
            (None, None),  # personal row exists but corrected_food_id is null
            (str(food_uuid), "x", 0.7),  # trigram catches it
        ]
    )
    matcher = HybridFoodMatcher(session=session, embedder=MagicMock())

    food_id, name_norm, method, corrected_g = await matcher.match(
        name="x",
        amount_g=50,
        locale="es",
        user_id=uuid4(),
    )

    assert food_id == food_uuid
    assert method == "trigram"
    assert corrected_g is None
