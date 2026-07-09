"""Infrastructure — load today's planned meal as a short ingredient string.

Injected into the LLM system prompt so the model can calibrate portion
estimates against the expected dish (feature F2.1).  Best-effort: returns
None on any DB error or when no active plan exists.

Must never be imported by the domain layer.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.shared.domain.time import utc_today

log = get_logger("vision.plan_context")


async def load_plan_context(
    *, user_id: UUID, meal_time: str, session: AsyncSession
) -> str | None:
    """Return a short ingredient list for today's planned meal.

    Format: ``"Recipe name: ingredient 100g, ingredient 50g"``
    or just the ingredient list when no recipe name is available.
    Returns None when the user has no active plan, or no matching meal slot.
    """
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT r.name_en,
                           rc.free_text_name,
                           rc.amount_g
                      FROM plan_meals pm
                      JOIN plan_days pd ON pd.id = pm.plan_day_id
                      JOIN plans p     ON p.id  = pd.plan_id
                      LEFT JOIN recipes r
                             ON r.id = pm.recipe_id
                      LEFT JOIN recipe_components rc
                             ON rc.recipe_id = pm.recipe_id
                     WHERE p.user_id  = :uid
                       AND p.status   = 'active'
                       AND pd.date    = :today
                       AND pm.meal_time = :mt
                     ORDER BY rc.position
                    """
                ),
                {"uid": str(user_id), "today": utc_today(), "mt": meal_time},
            )
        ).all()

        if not rows:
            return None

        recipe_name: str | None = rows[0][0] if rows[0][0] else None
        ingredients = [f"{r[1]} {int(r[2])}g" for r in rows if r[1] and r[2]]

        if not ingredients:
            return recipe_name

        parts = ", ".join(ingredients)
        return f"{recipe_name}: {parts}" if recipe_name else parts

    except Exception as exc:  # noqa: BLE001 — OK4: plan context is a best-effort LLM hint
        log.debug("vision.plan_context.failed", err=str(exc)[:120])
        return None
