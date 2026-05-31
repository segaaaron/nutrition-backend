"""Cross-check detected items vs the active plan meal for the given meal_time.

Returns a coach hint string (or None if no active plan / no expected meal).
Cheap deterministic check — no LLM. Coach feature B uses the hint as input
to a single mini call (or skips if the gap is < 15% kcal).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class ReconcileWithPlan:
    session: AsyncSession

    async def __call__(
        self,
        *,
        user_id: UUID,
        meal_time: str,
        detected_kcal: int,
    ) -> dict | None:
        row = (await self.session.execute(text("""
            SELECT pm.recipe_id::text, pm.kcal
              FROM plan_meals pm
              JOIN plan_days pd ON pd.id = pm.plan_day_id
              JOIN plans p ON p.id = pd.plan_id
             WHERE p.user_id = :uid AND p.status = 'active'
               AND pd.date = :today AND pm.meal_time = :mt
             LIMIT 1
        """), {"uid": str(user_id), "today": date.today(), "mt": meal_time})).first()
        if not row:
            return None
        planned_kcal = int(row[1] or 0)
        if planned_kcal == 0:
            return None
        delta_pct = (detected_kcal - planned_kcal) / planned_kcal
        return {
            "planned_recipe_id": row[0],
            "planned_kcal": planned_kcal,
            "detected_kcal": detected_kcal,
            "delta_pct": delta_pct,
            "needs_hint": abs(delta_pct) >= 0.15,
        }
