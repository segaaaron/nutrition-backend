"""Unit — ReconcileWithPlan use case.

Cheap deterministic plan-vs-detected comparison. Returns None when no
active plan exists; otherwise returns the delta hint payload.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.application.reconcile_with_plan import ReconcileWithPlan


def _execute_returning(row):
    """Build a session.execute mock whose result.first() returns row."""
    session = MagicMock()
    result = MagicMock()
    result.first = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_returns_none_when_no_active_plan_meal():
    session = _execute_returning(None)
    uc = ReconcileWithPlan(session=session)

    hint = await uc(user_id=uuid4(), meal_time="lunch", detected_kcal=600)

    assert hint is None


@pytest.mark.asyncio
async def test_returns_none_when_planned_kcal_is_zero():
    session = _execute_returning(("recipe-uuid", 0))
    uc = ReconcileWithPlan(session=session)

    hint = await uc(user_id=uuid4(), meal_time="lunch", detected_kcal=500)

    assert hint is None


@pytest.mark.asyncio
async def test_returns_hint_with_positive_delta_pct():
    session = _execute_returning(("recipe-abc", 500))
    uc = ReconcileWithPlan(session=session)

    hint = await uc(user_id=uuid4(), meal_time="dinner", detected_kcal=700)

    assert hint is not None
    assert hint["planned_recipe_id"] == "recipe-abc"
    assert hint["planned_kcal"] == 500
    assert hint["detected_kcal"] == 700
    assert hint["delta_pct"] == pytest.approx(0.4)
    assert hint["needs_hint"] is True  # 40% > 15% threshold


@pytest.mark.asyncio
async def test_no_hint_needed_when_within_threshold():
    session = _execute_returning(("recipe-abc", 500))
    uc = ReconcileWithPlan(session=session)

    hint = await uc(user_id=uuid4(), meal_time="breakfast", detected_kcal=525)

    assert hint is not None
    assert hint["needs_hint"] is False  # 5% < 15%


@pytest.mark.asyncio
async def test_negative_delta_when_underate():
    session = _execute_returning(("recipe-abc", 800))
    uc = ReconcileWithPlan(session=session)

    hint = await uc(user_id=uuid4(), meal_time="lunch", detected_kcal=400)

    assert hint is not None
    assert hint["delta_pct"] == pytest.approx(-0.5)
    assert hint["needs_hint"] is True


@pytest.mark.asyncio
async def test_hint_threshold_boundary_at_exactly_15pct():
    session = _execute_returning(("recipe-edge", 1000))
    uc = ReconcileWithPlan(session=session)

    hint = await uc(user_id=uuid4(), meal_time="lunch", detected_kcal=1150)

    assert hint is not None
    assert hint["delta_pct"] == pytest.approx(0.15)
    assert hint["needs_hint"] is True  # >= 15%
