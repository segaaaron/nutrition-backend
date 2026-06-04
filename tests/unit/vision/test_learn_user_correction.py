"""Unit — LearnUserCorrection use case.

Validates:
- The SQL statement is executed exactly once with normalized name.
- Name normalization strips diacritics, lowercases, collapses whitespace.
- UUIDs are stringified for binding.
- None values for corrected_food_id / corrected_amount_g pass through as None.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.vision.application.learn_user_correction import LearnUserCorrection, _norm


def test_norm_strips_diacritics():
    assert _norm("Plátano Maduro") == "platano maduro"


def test_norm_collapses_whitespace():
    assert _norm("  arroz   blanco  ") == "arroz blanco"


def test_norm_removes_punctuation():
    assert _norm("café con leche!") == "cafe con leche"


def test_norm_handles_empty():
    assert _norm("") == ""


def test_norm_only_punctuation_is_empty():
    assert _norm("!!!") == ""


@given(s=st.text())
def test_norm_is_idempotent(s: str) -> None:
    assert _norm(_norm(s)) == _norm(s)


@given(s=st.text())
def test_norm_output_has_no_uppercase(s: str) -> None:
    out = _norm(s)
    assert out == out.lower()


@pytest.mark.asyncio
async def test_executes_upsert_with_normalized_name():
    session = MagicMock()
    session.execute = AsyncMock()
    uc = LearnUserCorrection(session=session)

    user_id = uuid4()
    food_id = uuid4()
    await uc(
        user_id=user_id,
        detected_name="Plátano",
        corrected_food_id=food_id,
        corrected_amount_g=Decimal("120.5"),
    )

    session.execute.assert_awaited_once()
    _, kwargs = session.execute.call_args
    # kwargs[1] is the params dict
    params = session.execute.call_args[0][1]
    assert params["uid"] == str(user_id)
    assert params["n"] == "platano"
    assert params["fid"] == str(food_id)
    assert params["ag"] == 120.5


@pytest.mark.asyncio
async def test_passes_none_when_no_correction_food():
    session = MagicMock()
    session.execute = AsyncMock()
    uc = LearnUserCorrection(session=session)

    await uc(
        user_id=uuid4(),
        detected_name="x",
        corrected_food_id=None,
        corrected_amount_g=None,
    )

    params = session.execute.call_args[0][1]
    assert params["fid"] is None
    assert params["ag"] is None
