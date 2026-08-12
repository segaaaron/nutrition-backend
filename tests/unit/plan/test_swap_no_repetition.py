"""`SwapMeal` must honour the anti-repetition window (CLAUDE.md §REGLA D).

Regression for the PROD incident found 2026-07-17: the owner's active plan
served 21 distinct recipes out of the generator, then swaps reintroduced 3
repetitions — two of them back-to-back (dinner on days 1+2, lunch on days
5+6). Every repeated pair had exactly one member with `swapped_from` set.

Root cause: `SwapMeal` compared the replacement only against the meal it was
replacing, never against the rest of the plan. `CreatePlan` maintains a
rolling `forbidden` window; the swap path had no equivalent, so it happily
picked a recipe already sitting in the same slot on another day.

REGLA D is explicit that variety here is a requirement, not a preference:
when the pool cannot satisfy it, abort naming the slot rather than repeat
silently.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.errors import BusinessRuleViolation
from app.plan.application.use_cases import SwapMeal
from app.plan.domain.entities import Plan, PlanDay, PlanMeal

_LUNCH_A = uuid4()  # sits at day 6 — a swap at day 5 must not land here
_LUNCH_B = uuid4()  # sits at day 0 — far away in a month plan, near in a week
_FREE = uuid4()  # unused anywhere: the only legal pick


def _meal(meal_time: str, recipe_id: UUID | None, day_id: UUID) -> PlanMeal:
    return PlanMeal(
        id=uuid4(),
        plan_day_id=day_id,
        meal_time=meal_time,  # type: ignore[arg-type]
        recipe_id=recipe_id,
        kcal=700,
        protein_g=40,
        carbs_g=70,
        fat_g=20,
    )


def _plan(total_days: int = 7) -> tuple[Plan, UUID]:
    """A plan whose day-5 lunch is the swap target. Returns (plan, meal_id)."""
    plan_id = uuid4()
    days: list[PlanDay] = []
    target_meal_id: UUID | None = None
    for d in range(total_days):
        day_id = uuid4()
        recipe = {0: _LUNCH_B, 6: _LUNCH_A}.get(d, uuid4())
        lunch = _meal("lunch", recipe, day_id)
        # Same recipe in a DIFFERENT slot must not constrain the lunch swap.
        dinner = _meal("dinner", _FREE, day_id)
        if d == 5:
            target_meal_id = lunch.id
        days.append(
            PlanDay(
                id=day_id,
                plan_id=plan_id,
                day_index=d,
                date=date(2026, 7, 11),
                meals=[lunch, dinner],
            )
        )
    plan = Plan(
        id=plan_id,
        user_id=uuid4(),
        type="week",  # type: ignore[arg-type]
        total_days=total_days,
        current_day=1,
        status="active",  # type: ignore[arg-type]
        goal=None,
        meals_per_day=3,
        preferences=[],
        kcal_target=1665,
        version=0,
        created_at=datetime.now(UTC),
        days=days,
    )
    assert target_meal_id is not None
    return plan, target_meal_id


class _StubPlans:
    def __init__(self, plan: Plan) -> None:
        self._plan = plan
        self.swapped: list[tuple[UUID, UUID]] = []

    async def get(self, plan_id: UUID) -> Plan:
        return self._plan

    async def swap_meal_recipe(self, meal_id: UUID, new_recipe_id: UUID) -> None:
        self.swapped.append((meal_id, new_recipe_id))


class _StubCache:
    async def invalidate(self, user_id: UUID) -> None:
        return None


class _StubBus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


class _StubLayer3:
    """Ranks by the order handed in — so a leaked candidate would win."""

    def __init__(self) -> None:
        self.seen_candidates: list[UUID] = []

    async def __call__(
        self, *, user_id: UUID, candidate_ids: list[UUID], meal_time: str, **_: Any
    ) -> list[tuple[UUID, float]]:
        self.seen_candidates = list(candidate_ids)
        return [(rid, 1.0 - i) for i, rid in enumerate(candidate_ids)]


def _swap(plan: Plan) -> tuple[SwapMeal, _StubPlans, _StubLayer3]:
    plans = _StubPlans(plan)
    layer3 = _StubLayer3()
    uc = SwapMeal(plans=plans, cache=_StubCache(), layer3=layer3, bus=_StubBus())  # type: ignore[arg-type]
    return uc, plans, layer3


@pytest.mark.asyncio
async def test_swap_never_picks_recipe_already_in_same_slot() -> None:
    """The exact PROD failure: day-5 lunch swap must not land on day 6's."""
    plan, meal_id = _plan()
    uc, plans, layer3 = _swap(plan)

    # _LUNCH_A ranks first, so only the window filter can keep it out.
    await uc(
        plan_id=plan.id,
        meal_id=meal_id,
        reason_code="dislike",
        candidate_ids=[_LUNCH_A, _FREE],
    )

    assert _LUNCH_A not in layer3.seen_candidates, "day-6 lunch leaked into candidates"
    assert plans.swapped == [(meal_id, _FREE)]


@pytest.mark.asyncio
async def test_swap_window_is_symmetric_not_only_backwards() -> None:
    """Day 6 is AHEAD of day 5. A backwards-only window would miss it."""
    plan, meal_id = _plan()
    uc, _plans, layer3 = _swap(plan)

    await uc(
        plan_id=plan.id,
        meal_id=meal_id,
        reason_code="dislike",
        candidate_ids=[_LUNCH_A, _FREE],
    )

    assert _LUNCH_A not in layer3.seen_candidates


@pytest.mark.asyncio
async def test_swap_ignores_other_slots() -> None:
    """A recipe used at dinner is still legal at lunch — window is per-slot."""
    plan, meal_id = _plan()
    uc, plans, layer3 = _swap(plan)

    await uc(
        plan_id=plan.id,
        meal_id=meal_id,
        reason_code="dislike",
        candidate_ids=[_FREE],
    )

    assert _FREE in layer3.seen_candidates
    assert plans.swapped == [(meal_id, _FREE)]


@pytest.mark.asyncio
async def test_swap_fails_loudly_when_pool_exhausted() -> None:
    """REGLA D: abort naming the slot — never relax and repeat in silence."""
    plan, meal_id = _plan()
    uc, plans, _layer3 = _swap(plan)

    with pytest.raises(BusinessRuleViolation) as exc:
        await uc(
            plan_id=plan.id,
            meal_id=meal_id,
            reason_code="dislike",
            candidate_ids=[_LUNCH_A, _LUNCH_B],
        )

    assert "swap_pool_exhausted_for_slot" in str(exc.value)
    assert plans.swapped == [], "must not persist a repeat when aborting"


@pytest.mark.asyncio
async def test_swap_week_window_excludes_day0_recipe_at_day5() -> None:
    """Week window=7: day 0 is inside a day-5 swap's window (|5-0|=5 < 7)."""
    plan, meal_id = _plan(total_days=7)
    uc, _plans, layer3 = _swap(plan)

    await uc(
        plan_id=plan.id,
        meal_id=meal_id,
        reason_code="dislike",
        candidate_ids=[_LUNCH_B, _FREE],
    )

    # day 0 recipe is within the 7-day window → must be excluded.
    assert _LUNCH_B not in layer3.seen_candidates
