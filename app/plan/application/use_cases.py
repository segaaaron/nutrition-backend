"""Plan use cases: get/advance/complete/swap/regenerate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.event_bus import EventBus
from app.plan.application.layer3_ranking import Layer3Ranking
from app.plan.domain.entities import Plan
from app.plan.domain.events import (
    DayCompleted,
    MealCompleted,
    MealSwapped,
    PlanCompleted,
    PlanRegenerated,
)
from app.plan.domain.state_machine import advance
from app.plan.infrastructure.cache import ActivePlanCache
from app.plan.infrastructure.repositories import SqlPlanRepository


@dataclass(slots=True)
class GetActivePlan:
    plans: SqlPlanRepository
    cache: ActivePlanCache

    async def __call__(self, *, user_id: UUID) -> Plan:
        plan = await self.plans.get_active(user_id)
        if plan is None:
            raise NotFoundError("no_active_plan", user_id=str(user_id))
        return plan


@dataclass(slots=True)
class AdvancePlan:
    plans: SqlPlanRepository
    cache: ActivePlanCache
    bus: EventBus

    async def __call__(self, *, plan_id: UUID, event: str) -> Plan:
        plan = await self.plans.get(plan_id)
        if plan is None:
            raise NotFoundError("plan_not_found", plan_id=str(plan_id))
        new_plan = advance(plan, event)  # type: ignore[arg-type]
        await self.plans.update_meta(new_plan)
        await self.cache.invalidate(plan.user_id)
        now = datetime.now(UTC)
        if new_plan.status == "completed" and plan.status == "active":
            await self.bus.publish(
                PlanCompleted(
                    plan_id=plan.id,
                    user_id=plan.user_id,
                    at=now,
                )
            )
        return new_plan


@dataclass(slots=True)
class CompleteMeal:
    plans: SqlPlanRepository
    cache: ActivePlanCache
    bus: EventBus

    async def __call__(self, *, plan_id: UUID, meal_id: UUID) -> None:
        plan = await self.plans.get(plan_id)
        if plan is None:
            raise NotFoundError("plan_not_found", plan_id=str(plan_id))
        meal = plan.find_meal(meal_id)
        if meal is None:
            raise NotFoundError("meal_not_found", meal_id=str(meal_id))
        await self.plans.mark_meal_completed(meal_id)
        await self.cache.invalidate(plan.user_id)
        now = datetime.now(UTC)
        await self.bus.publish(
            MealCompleted(
                plan_id=plan.id,
                user_id=plan.user_id,
                meal_id=meal_id,
                at=now,
            )
        )
        # Day completed when all meals of the meal's day are completed.
        for d in plan.days:
            if any(m.id == meal_id for m in d.meals):
                if all(m.completed or m.id == meal_id for m in d.meals):
                    await self.bus.publish(
                        DayCompleted(
                            plan_id=plan.id,
                            user_id=plan.user_id,
                            day_index=d.day_index,
                            at=now,
                        )
                    )
                break


# Anti-repetition window, mirroring CreatePlan: 7 days for day/week plans,
# 14 for month plans.
_SWAP_WINDOW_SHORT = 7
_SWAP_WINDOW_LONG = 14


def _window_recipe_ids(plan: Plan, meal_id: UUID, meal_time: str) -> set[UUID]:
    """Recipes already served in `meal_time` within the swapped meal's window.

    The window is SYMMETRIC, unlike CreatePlan's. CreatePlan builds days in
    order, so looking backwards is enough — nothing exists ahead of it yet. A
    swap lands in the middle of a finished plan, where a collision with a LATER
    day is just as much a repetition. Ignoring that direction is what let a
    day-5 lunch swap land on the recipe already sitting at day 6.
    """
    day_index = next(
        (d.day_index for d in plan.days for m in d.meals if m.id == meal_id), None
    )
    if day_index is None:
        return set()
    span = (_SWAP_WINDOW_SHORT if plan.total_days <= 7 else _SWAP_WINDOW_LONG) - 1
    return {
        m.recipe_id
        for d in plan.days
        if abs(d.day_index - day_index) <= span
        for m in d.meals
        if m.id != meal_id and m.meal_time == meal_time and m.recipe_id is not None
    }


@dataclass(slots=True)
class SwapMeal:
    plans: SqlPlanRepository
    cache: ActivePlanCache
    layer3: Layer3Ranking
    bus: EventBus

    async def __call__(
        self,
        *,
        plan_id: UUID,
        meal_id: UUID,
        reason_code: str,
        candidate_ids: list[UUID],
    ) -> list[UUID]:
        plan = await self.plans.get(plan_id)
        if plan is None:
            raise NotFoundError("plan_not_found", plan_id=str(plan_id))
        meal = plan.find_meal(meal_id)
        if meal is None:
            raise NotFoundError("meal_not_found", meal_id=str(meal_id))
        # CLAUDE.md §REGLA D — a plan must never repeat a recipe inside its
        # window, and variety is a requirement, not a preference. Comparing
        # only against the meal being replaced (the old behaviour) let a swap
        # reintroduce a recipe the generator had deliberately excluded. When
        # the pool cannot honour the rule, fail loudly naming the slot rather
        # than serving a silent repeat.
        forbidden = _window_recipe_ids(plan, meal_id, meal.meal_time)
        eligible = [rid for rid in candidate_ids if rid not in forbidden]
        if not eligible:
            raise BusinessRuleViolation(
                "swap_pool_exhausted_for_slot",
                meal_time=meal.meal_time,
                plan_id=str(plan_id),
                meal_id=str(meal_id),
                n_candidates=len(candidate_ids),
                n_forbidden=len(forbidden),
            )
        ranked = await self.layer3(
            user_id=plan.user_id,
            candidate_ids=eligible,
            meal_time=meal.meal_time,
        )
        top = [rid for rid, _ in ranked[:3]]
        if top and meal.recipe_id and top[0] != meal.recipe_id:
            await self.plans.swap_meal_recipe(meal_id, top[0])
            await self.cache.invalidate(plan.user_id)
            await self.bus.publish(
                MealSwapped(
                    plan_id=plan.id,
                    meal_id=meal_id,
                    from_recipe_id=meal.recipe_id,
                    to_recipe_id=top[0],
                    reason_code=reason_code,
                    at=datetime.now(UTC),
                )
            )
        return top


@dataclass(slots=True)
class RegenerateRemaining:
    plans: SqlPlanRepository
    cache: ActivePlanCache
    bus: EventBus

    async def __call__(self, *, plan_id: UUID) -> None:
        plan = await self.plans.get(plan_id)
        if plan is None:
            raise NotFoundError("plan_not_found", plan_id=str(plan_id))
        new_plan = advance(plan, "REGENERATE")
        await self.plans.update_meta(new_plan)
        await self.cache.invalidate(plan.user_id)
        await self.bus.publish(
            PlanRegenerated(
                plan_id=plan.id,
                user_id=plan.user_id,
                at=datetime.now(UTC),
            )
        )
