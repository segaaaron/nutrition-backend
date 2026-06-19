"""SqlPlanRepository — async repo with selectinload chain (days → meals)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.plan.domain.entities import Plan, PlanDay, PlanMeal
from app.plan.infrastructure.models import (
    PlanDayModel,
    PlanGenerationSeedModel,
    PlanMealModel,
    PlanModel,
)
from app.recipes.infrastructure.models import RecipeModel


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
        scaled_factor=float(m.scaled_factor) if m.scaled_factor is not None else None,
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

    async def fetch_recipe_macros(
        self, recipe_ids: list[UUID]
    ) -> dict[UUID, tuple[int | None, int | None, int | None, int | None]]:
        """Batch-fetch (kcal, protein_g, carbs_g, fat_g) per recipe id.

        Used by `CreatePlan` to populate per-meal macros after Layer3 picks
        a recipe for each slot. A single round-trip avoids N+1 — typical
        plan has 21 meals but only ~10-15 unique recipes due to weekly
        repetition. Returns a tuple per id; missing rows are omitted so
        callers can fall back to `None` safely.
        """
        if not recipe_ids:
            return {}
        unique_ids = list({rid for rid in recipe_ids})
        stmt = select(
            RecipeModel.id,
            RecipeModel.kcal,
            RecipeModel.protein_g,
            RecipeModel.carbs_g,
            RecipeModel.fat_g,
        ).where(RecipeModel.id.in_(unique_ids))
        rows = (await self.s.execute(stmt)).all()
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}

    async def count_recent_recipe_occurrences(
        self, user_id: UUID, *, days: int = 30
    ) -> dict[UUID, int]:
        """Recipe → times it appeared in this user's plans recently.

        Feeds the Layer3 `novelty` signal (1 - n/10): recipes the user has
        seen often in the last `days` rank lower, so consecutive plan
        generations rotate the catalog instead of repeating the same
        top-ranked dishes.
        """
        res = await self.s.execute(
            text(
                """
                SELECT pm.recipe_id, COUNT(*) AS n
                  FROM plan_meals pm
                  JOIN plan_days pd ON pd.id = pm.plan_day_id
                  JOIN plans p ON p.id = pd.plan_id
                 WHERE p.user_id = :uid
                   AND pm.recipe_id IS NOT NULL
                   AND pd.date >= CURRENT_DATE - CAST(:days AS int)
                 GROUP BY pm.recipe_id
                """
            ),
            {"uid": str(user_id), "days": days},
        )
        return {row[0]: int(row[1]) for row in res.all()}

    async def recipe_completion_rates(
        self, user_id: UUID, *, days: int = 90
    ) -> dict[UUID, float]:
        """Recipe → fraction of its plan appearances the user completed.

        Feeds the Layer3 `adherence` signal: recipes the user actually
        eats rank higher than ones they skip. Only recipes with at least
        3 appearances are returned — below that the rate is noise and the
        cold-start default (0.5) is more honest.
        """
        res = await self.s.execute(
            text(
                """
                SELECT pm.recipe_id,
                       COUNT(*) AS n,
                       AVG(CASE WHEN pm.completed THEN 1.0 ELSE 0.0 END) AS rate
                  FROM plan_meals pm
                  JOIN plan_days pd ON pd.id = pm.plan_day_id
                  JOIN plans p ON p.id = pd.plan_id
                 WHERE p.user_id = :uid
                   AND pm.recipe_id IS NOT NULL
                   AND pd.date >= CURRENT_DATE - CAST(:days AS int)
                   AND pd.date < CURRENT_DATE
                 GROUP BY pm.recipe_id
                HAVING COUNT(*) >= 3
                """
            ),
            {"uid": str(user_id), "days": days},
        )
        return {row[0]: float(row[2]) for row in res.all()}

    async def acquire_user_lock(self, user_id: UUID) -> None:
        """Serialize concurrent plan generation for a single user.

        Postgres advisory xact lock keyed on a stable hash of `user_id`.
        Released automatically on tx commit/rollback. Without it, two
        concurrent worker jobs for the same user (backlog drain, double-tap,
        retry storm) can both pass the `get_active` check and race the
        `one_active_plan` partial unique index → IntegrityError 500 to iOS.
        """
        await self.s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": str(user_id)},
        )

    async def archive_active(self, user_id: UUID) -> int:
        """Cancel the user's currently-active plan (if any).

        Returns the rowcount. Used by `CreatePlan` to make plan generation
        idempotent-by-user: an existing active plan is archived BEFORE the
        new one is inserted, preserving the `one_active_plan` invariant
        under any retry / concurrent-job scenario.
        """
        result = await self.s.execute(
            update(PlanModel)
            .where(PlanModel.user_id == user_id, PlanModel.status == "active")
            .values(status="cancelled")
        )
        return result.rowcount or 0

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
                        scaled_factor=meal.scaled_factor,
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
