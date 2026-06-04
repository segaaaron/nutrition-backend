"""SqlPlanRepository — async repo with selectinload chain (days → meals)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.plan.domain.entities import Plan, PlanDay, PlanMeal
from app.plan.infrastructure.models import (
    PlanDayModel,
    PlanGenerationSeedModel,
    PlanMealModel,
    PlanModel,
)


def _meal_from_model(m: PlanMealModel) -> PlanMeal:
    return PlanMeal(
        id=m.id,
        plan_day_id=m.plan_day_id,
        meal_time=m.meal_time,  # type: ignore[arg-type]
        recipe_id=m.recipe_id,
        kcal=m.kcal,
        protein_g=m.protein_g,
        carbs_g=m.carbs_g,
        fat_g=m.fat_g,
        water_ml=m.water_ml,
        water_pct=float(m.water_pct) if m.water_pct is not None else None,
        completed=m.completed,
        swapped_from=m.swapped_from,
    )


def _day_from_model(d: PlanDayModel) -> PlanDay:
    return PlanDay(
        id=d.id,
        plan_id=d.plan_id,
        day_index=d.day_index,
        date=d.date,
        completed=d.completed,
        meals=[_meal_from_model(m) for m in (d.meals or [])],
    )


def _plan_from_model(m: PlanModel) -> Plan:
    return Plan(
        id=m.id,
        user_id=m.user_id,
        type=m.type,  # type: ignore[arg-type]
        total_days=m.total_days,
        current_day=m.current_day,
        status=m.status,  # type: ignore[arg-type]
        goal=m.goal,
        meals_per_day=m.meals_per_day,
        preferences=list(m.preferences or []),
        kcal_target=m.kcal_target,
        version=m.version,
        created_at=m.created_at,
        days=[_day_from_model(d) for d in (m.days or [])],
    )


class SqlPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, plan_id: UUID, *, hydrate: bool = True) -> Plan | None:
        stmt = select(PlanModel).where(PlanModel.id == plan_id)
        if hydrate:
            stmt = stmt.options(selectinload(PlanModel.days).selectinload(PlanDayModel.meals))
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _plan_from_model(m) if m else None

    async def get_active(self, user_id: UUID) -> Plan | None:
        stmt = (
            select(PlanModel)
            .where(PlanModel.user_id == user_id, PlanModel.status == "active")
            .options(selectinload(PlanModel.days).selectinload(PlanDayModel.meals))
        )
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _plan_from_model(m) if m else None

    async def save(self, plan: Plan) -> Plan:
        m = PlanModel(
            id=plan.id,
            user_id=plan.user_id,
            type=plan.type,
            total_days=plan.total_days,
            current_day=plan.current_day,
            status=plan.status,
            goal=plan.goal,
            meals_per_day=plan.meals_per_day,
            preferences=plan.preferences,
            kcal_target=plan.kcal_target,
            version=plan.version,
            created_at=plan.created_at,
        )
        for d in plan.days:
            dm = PlanDayModel(
                id=d.id,
                plan_id=plan.id,
                day_index=d.day_index,
                date=d.date,
                completed=d.completed,
            )
            for meal in d.meals:
                dm.meals.append(
                    PlanMealModel(
                        id=meal.id,
                        plan_day_id=d.id,
                        meal_time=meal.meal_time,
                        recipe_id=meal.recipe_id,
                        kcal=meal.kcal,
                        protein_g=meal.protein_g,
                        carbs_g=meal.carbs_g,
                        fat_g=meal.fat_g,
                        water_ml=meal.water_ml,
                        water_pct=meal.water_pct,
                        completed=meal.completed,
                        swapped_from=meal.swapped_from,
                    )
                )
            m.days.append(dm)
        self.s.add(m)
        await self.s.flush()
        return plan

    async def update_meta(self, plan: Plan) -> None:
        await self.s.execute(
            update(PlanModel)
            .where(PlanModel.id == plan.id)
            .values(
                status=plan.status,
                current_day=plan.current_day,
                version=plan.version,
            )
        )

    async def mark_meal_completed(self, meal_id: UUID) -> None:
        await self.s.execute(
            update(PlanMealModel).where(PlanMealModel.id == meal_id).values(completed=True)
        )

    async def swap_meal_recipe(self, meal_id: UUID, new_recipe_id: UUID) -> None:
        # Capture current recipe → swapped_from in a single statement to avoid
        # a read+write race.
        await self.s.execute(
            update(PlanMealModel)
            .where(PlanMealModel.id == meal_id)
            .values(swapped_from=PlanMealModel.recipe_id, recipe_id=new_recipe_id)
        )

    async def save_seed(self, plan_id: UUID, seed: int) -> None:
        self.s.add(PlanGenerationSeedModel(plan_id=plan_id, seed=seed))
        await self.s.flush()
