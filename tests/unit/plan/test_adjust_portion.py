"""Unit tests for AdjustPortion use case (BE-11)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.plan.application.use_cases import AdjustPortion
from app.plan.domain.entities import Plan, PlanDay, PlanMeal
from app.plan.infrastructure.cache import ActivePlanCache
from app.plan.infrastructure.repositories import SqlPlanRepository


def _make_plan(meal_kcal: int = 400, protein_g: int = 35, completed: bool = False) -> Plan:
    meal_id = uuid.uuid4()
    day_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    meal = PlanMeal(
        id=meal_id,
        plan_day_id=day_id,
        meal_time="lunch",
        recipe_id=uuid.uuid4(),
        kcal=meal_kcal,
        protein_g=protein_g,
        carbs_g=50,
        fat_g=10,
        completed=completed,
    )
    day = PlanDay(
        id=day_id,
        plan_id=plan_id,
        day_index=0,
        date=date.today(),
        meals=[meal],
    )
    return Plan(
        id=plan_id,
        user_id=uuid.uuid4(),
        type="week",
        total_days=7,
        current_day=1,
        status="active",
        goal="weight_loss",
        meals_per_day=3,
        preferences=[],
        kcal_target=1800,
        version=1,
        created_at=datetime.now(UTC),
        days=[day],
    )


def _make_uc(plan: Plan | None) -> tuple[AdjustPortion, AsyncMock, AsyncMock]:
    repo = AsyncMock(spec=SqlPlanRepository)
    repo.get = AsyncMock(return_value=plan)
    repo.set_user_factor = AsyncMock()
    cache = AsyncMock(spec=ActivePlanCache)
    cache.invalidate = AsyncMock()
    return AdjustPortion(plans=repo, cache=cache), repo, cache


# ── happy path ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_factor_persists_and_returns_meal():
    plan = _make_plan()
    meal = plan.days[0].meals[0]
    uc, repo, cache = _make_uc(plan)

    result_meal, warnings = await uc(
        plan_id=plan.id,
        meal_id=meal.id,
        user_factor=0.75,
        user_goal="weight_loss",
    )

    repo.set_user_factor.assert_awaited_once_with(meal.id, 0.75)
    cache.invalidate.assert_awaited_once_with(plan.user_id)
    assert result_meal.user_factor == 0.75
    assert warnings == []  # 35g * 0.75 = 26g >= 25g threshold


@pytest.mark.asyncio
async def test_factor_1_5_no_warning():
    plan = _make_plan(protein_g=28)
    meal = plan.days[0].meals[0]
    uc, _, _ = _make_uc(plan)

    _, warnings = await uc(
        plan_id=plan.id,
        meal_id=meal.id,
        user_factor=1.5,
        user_goal="weight_loss",
    )
    assert warnings == []  # 28 * 1.5 = 42g >= 25g


# ── leucine threshold warning ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leucine_warning_when_protein_too_low():
    plan = _make_plan(protein_g=30)  # 30 * 0.5 = 15g < 25g threshold
    meal = plan.days[0].meals[0]
    uc, _, _ = _make_uc(plan)

    _, warnings = await uc(
        plan_id=plan.id,
        meal_id=meal.id,
        user_factor=0.5,
        user_goal="weight_loss",
    )
    assert "protein_below_leucine_threshold" in warnings


@pytest.mark.asyncio
async def test_leucine_warning_muscle_gain_higher_threshold():
    plan = _make_plan(protein_g=35)  # 35 * 0.75 = 26g < 30g (muscle_gain threshold)
    meal = plan.days[0].meals[0]
    uc, _, _ = _make_uc(plan)

    _, warnings = await uc(
        plan_id=plan.id,
        meal_id=meal.id,
        user_factor=0.75,
        user_goal="muscle_gain",
    )
    assert "protein_below_leucine_threshold" in warnings


@pytest.mark.asyncio
async def test_no_leucine_warning_for_snack_slot():
    """Leucine threshold only applies to main meal slots, not snacks."""
    plan = _make_plan(protein_g=10)
    plan.days[0].meals[0].meal_time = "morning_snack"
    meal = plan.days[0].meals[0]
    uc, _, _ = _make_uc(plan)

    _, warnings = await uc(
        plan_id=plan.id,
        meal_id=meal.id,
        user_factor=0.25,
        user_goal="weight_loss",
    )
    assert warnings == []


# ── validation errors ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_factor_not_quarter_multiple_raises():
    plan = _make_plan()
    meal = plan.days[0].meals[0]
    uc, _, _ = _make_uc(plan)

    with pytest.raises(BusinessRuleViolation) as exc_info:
        await uc(plan_id=plan.id, meal_id=meal.id, user_factor=0.3)
    assert exc_info.value.args[0] == "user_factor_not_quarter"


@pytest.mark.asyncio
async def test_factor_out_of_range_raises():
    plan = _make_plan()
    meal = plan.days[0].meals[0]
    uc, _, _ = _make_uc(plan)

    with pytest.raises(BusinessRuleViolation) as exc_info:
        await uc(plan_id=plan.id, meal_id=meal.id, user_factor=2.25)
    assert exc_info.value.args[0] == "user_factor_out_of_range"


@pytest.mark.asyncio
async def test_completed_meal_raises():
    plan = _make_plan(completed=True)
    meal = plan.days[0].meals[0]
    uc, _, _ = _make_uc(plan)

    with pytest.raises(BusinessRuleViolation) as exc_info:
        await uc(plan_id=plan.id, meal_id=meal.id, user_factor=0.75)
    assert exc_info.value.args[0] == "meal_already_completed"


@pytest.mark.asyncio
async def test_plan_not_found_raises():
    uc, _, _ = _make_uc(None)

    with pytest.raises(NotFoundError):
        await uc(plan_id=uuid.uuid4(), meal_id=uuid.uuid4(), user_factor=1.0)


@pytest.mark.asyncio
async def test_meal_not_found_raises():
    plan = _make_plan()
    uc, _, _ = _make_uc(plan)

    with pytest.raises(NotFoundError):
        await uc(plan_id=plan.id, meal_id=uuid.uuid4(), user_factor=1.0)


# ── boundary values ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("factor", [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0])
async def test_all_valid_factors_accepted(factor: float):
    plan = _make_plan()
    meal = plan.days[0].meals[0]
    uc, repo, _ = _make_uc(plan)

    _, _ = await uc(plan_id=plan.id, meal_id=meal.id, user_factor=factor)
    repo.set_user_factor.assert_awaited_once_with(meal.id, factor)
