"""Camino 1 — deterministic template responses (zero LLM cost, 40% traffic target).

Each handler takes a ``(user_id, session, locale)`` triple and returns a string
ready to render. ``None`` ⇒ template can't compute (fall through to Camino 3).

Locale-aware messages live in ``MESSAGES_ES`` / ``MESSAGES_EN`` module-level
dicts (pattern: ``app/plan/domain/water_view.py:_MESSAGES``). Adding a new
locale = add a row in :data:`MESSAGES_REGISTRY`, no code branches.

Hot-path: ``MESSAGES_REGISTRY[locale][key]`` is an O(1) dict lookup, no DB.
Per plan D9, the Translator (DB-backed) is reserved for closed vocabularies
(allergens, conditions, goals) — NOT for these template strings.

Tone contract: every message complies with ``docs/product/COACH_TONE.md`` —
positive framing, forward-action, no punitive language.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.coach.domain.value_objects import Intent

# Direct submodule import — avoid the ``app.shared.i18n`` package facade
# which pulls in FastAPI-only ``fastapi_dep`` (and via identity, this very
# application module) creating an import cycle.
from app.shared.i18n.locale_resolver import Locale

# ---------------------------------------------------------------------------
# Locale-aware message catalogue
# ---------------------------------------------------------------------------
#
# Keys are stable identifiers consumed by render helpers below. Both dicts
# MUST have the SAME key set (enforced by
# ``tests/unit/coach/test_template_parity.py``). To add a locale, copy the
# whole dict and translate each value; no code change beyond
# :data:`MESSAGES_REGISTRY`.

MESSAGES_ES: Final[dict[str, str]] = {
    # view_today_plan
    "today_plan_header": "Tu plan de hoy:\n",
    "today_plan_line": "- {meal_time}: {name} ({kcal} kcal)",
    # next_meal
    "next_meal": "Tu próxima comida: {meal_time} → {name} ({kcal} kcal)",
    # streak_status
    "streak_empty": "Aún no tienes racha activa. ¡Empieza hoy! 🌱",
    "streak_header": "Rachas:\n",
    "streak_line": "{kind}: {value} días",
    # water_progress
    "water_goal_hit": "¡Meta cumplida! {total} ml de {goal} ml ({pct}%). 💪",
    "water_in_progress": (
        "Vas {total} ml de {goal} ml ({pct}%), buen ritmo. "
        "Te faltan {remaining} ml para cerrar el día."
    ),
    "water_no_goal": "{total} ml hoy.",
    # protein_remaining
    "protein_remaining": "Te quedan ~{remaining} g de proteína hoy ({consumed}/{goal}).",
    # mark_water
    "water_logged": "Registré 250 ml de agua. ¡Sigue así! 💪",
    # placeholder for missing meal name
    "meal_name_unknown": "—",
}

MESSAGES_EN: Final[dict[str, str]] = {
    # view_today_plan
    "today_plan_header": "Today's plan:\n",
    "today_plan_line": "- {meal_time}: {name} ({kcal} kcal)",
    # next_meal
    "next_meal": "Next meal: {meal_time} → {name} ({kcal} kcal)",
    # streak_status
    "streak_empty": "No active streak yet. Start today! 🌱",
    "streak_header": "Streaks:\n",
    "streak_line": "{kind}: {value} days",
    # water_progress
    "water_goal_hit": "Goal hit! {total} ml of {goal} ml ({pct}%). 💪",
    "water_in_progress": (
        "You're at {total} ml of {goal} ml ({pct}%), nice pace. "
        "{remaining} ml to close out the day."
    ),
    "water_no_goal": "{total} ml today.",
    # protein_remaining
    "protein_remaining": "~{remaining} g of protein remaining ({consumed}/{goal}).",
    # mark_water
    "water_logged": "Logged 250 ml of water. Keep it up! 💪",
    # placeholder for missing meal name
    "meal_name_unknown": "—",
}

MESSAGES_REGISTRY: Final[dict[Locale, dict[str, str]]] = {
    "es": MESSAGES_ES,
    "en": MESSAGES_EN,
}


def _render(locale: Locale, key: str, /, **kwargs: object) -> str:
    """Lookup + format a localized message.

    Args:
        locale: One of :data:`app.shared.i18n.SUPPORTED_LOCALES`.
        key: Message key present in every registry dict (parity-tested).
        **kwargs: Substitution values for ``str.format``.

    Returns:
        Rendered message string.
    """
    # Defensive fallback to ES if the caller smuggled an unsupported locale
    # past the type checker (e.g. via ``cast``). Keeps the contract that
    # this function never raises ``KeyError`` on locale.
    catalogue = MESSAGES_REGISTRY.get(locale) or MESSAGES_ES
    return catalogue[key].format(**kwargs)


# ---------------------------------------------------------------------------
# Template handlers
# ---------------------------------------------------------------------------


async def view_today_plan(user_id: UUID, session: AsyncSession, locale: Locale) -> str | None:
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
    unknown = _render(locale, "meal_name_unknown")
    lines = [
        _render(locale, "today_plan_line", meal_time=r[0], name=(r[1] or unknown), kcal=r[2])
        for r in rows
    ]
    return _render(locale, "today_plan_header") + "\n".join(lines)


async def next_meal(user_id: UUID, session: AsyncSession, locale: Locale) -> str | None:
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
    unknown = _render(locale, "meal_name_unknown")
    return _render(
        locale,
        "next_meal",
        meal_time=row[0],
        name=(row[1] or unknown),
        kcal=row[2],
    )


async def streak_status(user_id: UUID, session: AsyncSession, locale: Locale) -> str | None:
    rows = (
        await session.execute(
            text(
                """
        SELECT type, value FROM streaks WHERE user_id = :uid
    """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    if not rows:
        return _render(locale, "streak_empty")
    parts = [_render(locale, "streak_line", kind=r[0], value=r[1]) for r in rows]
    return _render(locale, "streak_header") + "\n".join(parts)


async def water_progress(user_id: UUID, session: AsyncSession, locale: Locale) -> str | None:
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
        remaining = max(0, int(goal) - int(total))
        # Coach tone — positive framing, never punitive. See docs/product/COACH_TONE.md.
        if pct >= 100:
            return _render(locale, "water_goal_hit", total=total, goal=goal, pct=pct)
        return _render(
            locale,
            "water_in_progress",
            total=total,
            goal=goal,
            pct=pct,
            remaining=remaining,
        )
    return _render(locale, "water_no_goal", total=total)


async def protein_remaining(user_id: UUID, session: AsyncSession, locale: Locale) -> str | None:
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
    return _render(
        locale,
        "protein_remaining",
        remaining=remaining,
        consumed=consumed,
        goal=goal,
    )


async def mark_water(user_id: UUID, session: AsyncSession, locale: Locale) -> str | None:
    # Imperative template — registers default 250ml.
    await session.execute(
        text(
            """
        INSERT INTO water_logs (time, user_id, ml) VALUES (now(), :uid, 250)
    """
        ),
        {"uid": str(user_id)},
    )
    return _render(locale, "water_logged")


TEMPLATES: Final[dict[Intent, Callable[[UUID, AsyncSession, Locale], Awaitable[str | None]]]] = {
    Intent.VIEW_TODAY_PLAN: view_today_plan,
    Intent.NEXT_MEAL: next_meal,
    Intent.STREAK_STATUS: streak_status,
    Intent.WATER_PROGRESS: water_progress,
    Intent.PROTEIN_REMAINING: protein_remaining,
    Intent.MARK_WATER: mark_water,
}
