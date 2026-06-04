"""Camino 1 — deterministic template responses (zero LLM cost, 40% traffic target).

Each handler takes a `(user_id, session, locale)` triple and returns a string
ready to render. None ⇒ template can't compute (fall through to Camino 3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.coach.domain.value_objects import Intent


async def view_today_plan(user_id: UUID, session: AsyncSession, locale: str) -> str | None:
    rows = (
        await session.execute(
            text(
                """
        SELECT pm.meal_time, r.name_en, COALESCE(pm.kcal, 0)
          FROM plan_meals pm
          JOIN plan_days pd ON pd.id = pm.plan_day_id
          JOIN plans p ON p.id = pd.plan_id
          LEFT JOIN recipes r ON r.id = pm.recipe_id
         WHERE p.user_id = :uid AND p.status = 'active' AND pd.date = :d
         ORDER BY array_position(ARRAY['breakfast','lunch','dinner','snack']::text[], pm.meal_time::text)
    """
            ),
            {"uid": str(user_id), "d": date.today()},
        )
    ).all()
    if not rows:
        return None
    lines = [f"- {r[0]}: {r[1] or '—'} ({r[2]} kcal)" for r in rows]
    return ("Tu plan de hoy:\n" if locale == "es" else "Today's plan:\n") + "\n".join(lines)


async def next_meal(user_id: UUID, session: AsyncSession, locale: str) -> str | None:
    row = (
        await session.execute(
            text(
                """
        SELECT pm.meal_time, r.name_en, COALESCE(pm.kcal, 0)
          FROM plan_meals pm
          JOIN plan_days pd ON pd.id = pm.plan_day_id
          JOIN plans p ON p.id = pd.plan_id
          LEFT JOIN recipes r ON r.id = pm.recipe_id
         WHERE p.user_id = :uid AND p.status = 'active' AND pd.date = :d
           AND pm.completed = false
         ORDER BY array_position(ARRAY['breakfast','lunch','dinner','snack']::text[], pm.meal_time::text)
         LIMIT 1
    """
            ),
            {"uid": str(user_id), "d": date.today()},
        )
    ).first()
    if not row:
        return None
    return (
        f"Tu próxima comida: {row[0]} → {row[1] or '—'} ({row[2]} kcal)"
        if locale == "es"
        else f"Next meal: {row[0]} → {row[1] or '—'} ({row[2]} kcal)"
    )


async def streak_status(user_id: UUID, session: AsyncSession, locale: str) -> str | None:
    row = (
        await session.execute(
            text(
                """
        SELECT type, value FROM streaks WHERE user_id = :uid
    """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    if not row:
        return (
            "Aún no tienes racha activa. ¡Empieza hoy!"
            if locale == "es"
            else "No active streak yet."
        )
    parts = [f"{r[0]}: {r[1]} días" if locale == "es" else f"{r[0]}: {r[1]} days" for r in row]
    return ("Rachas:\n" if locale == "es" else "Streaks:\n") + "\n".join(parts)


async def water_progress(user_id: UUID, session: AsyncSession, locale: str) -> str | None:
    from datetime import datetime

    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        (
            await session.execute(
                text(
                    """
        SELECT COALESCE(SUM(ml),0)::int FROM water_logs
         WHERE user_id = :uid AND time >= :s
    """
                ),
                {"uid": str(user_id), "s": today_start},
            )
        ).scalar()
        or 0
    )
    goal = (
        await session.execute(
            text(
                """
        SELECT water_ml FROM nutritional_goals
         WHERE user_id = :uid AND valid_to IS NULL
    """
            ),
            {"uid": str(user_id)},
        )
    ).scalar()
    if goal:
        pct = int(100 * total / max(1, goal))
        return (
            f"Llevas {total} ml de {goal} ml ({pct}%)."
            if locale == "es"
            else f"You've drunk {total} ml of {goal} ml ({pct}%)."
        )
    return f"{total} ml hoy." if locale == "es" else f"{total} ml today."


async def protein_remaining(user_id: UUID, session: AsyncSession, locale: str) -> str | None:
    goal = (
        await session.execute(
            text(
                """
        SELECT protein_g FROM nutritional_goals
         WHERE user_id = :uid AND valid_to IS NULL
    """
            ),
            {"uid": str(user_id)},
        )
    ).scalar()
    if not goal:
        return None
    consumed = (
        (
            await session.execute(
                text(
                    """
        SELECT COALESCE(SUM(protein_g),0)::int FROM food_logs
         WHERE user_id = :uid AND date = CURRENT_DATE
    """
                ),
                {"uid": str(user_id)},
            )
        ).scalar()
        or 0
    )
    remaining = max(0, int(goal) - int(consumed))
    return (
        f"Te quedan ~{remaining} g de proteína hoy ({consumed}/{goal})."
        if locale == "es"
        else f"~{remaining} g of protein remaining ({consumed}/{goal})."
    )


async def mark_water(user_id: UUID, session: AsyncSession, locale: str) -> str | None:
    # Imperative template — registers default 250ml.
    await session.execute(
        text(
            """
        INSERT INTO water_logs (time, user_id, ml) VALUES (now(), :uid, 250)
    """
        ),
        {"uid": str(user_id)},
    )
    return "Registré 250 ml de agua. ¡Sigue así!" if locale == "es" else "Logged 250 ml of water."


TEMPLATES: dict[Intent, Callable[[UUID, AsyncSession, str], Awaitable[str | None]]] = {
    Intent.VIEW_TODAY_PLAN: view_today_plan,
    Intent.NEXT_MEAL: next_meal,
    Intent.STREAK_STATUS: streak_status,
    Intent.WATER_PROGRESS: water_progress,
    Intent.PROTEIN_REMAINING: protein_remaining,
    Intent.MARK_WATER: mark_water,
}
