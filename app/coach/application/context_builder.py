"""Build the ~600-token ContextWindow for Camino 3 grounded calls.

Sources:
  - user_profiles (compact: age, sex, goal, allergies count, conditions count).
  - active plan today (meal_time → recipe name + kcal).
  - last 3 food_logs (name + kcal).
  - top 5 recipe matches via embedding cosine on the user message.
  - last 4 conversation messages.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.coach.domain.value_objects import ContextWindow
from app.coach.infrastructure.prompt_sanitizer import (
    PromptInjectionDetected,
    sanitize_for_prompt,
)
from app.coach.infrastructure.repositories import SqlConversationRepository
from app.core.logging import get_logger
from app.recipes.infrastructure.openai_embedder import OpenAIEmbedder
from app.shared.domain.time import utc_today

log = get_logger("coach.context_builder")

# Per-field caps. Names tight, free-text wider.
_RECIPE_NAME_MAX = 200
_FOOD_NAME_MAX = 100
_MEAL_NAME_MAX = 200
_MESSAGE_MAX = 500


def _safe(value: str | None, *, max_len: int, field: str) -> str | None:
    """Sanitise a catalog/free-text string for prompt interpolation.

    Returns ``None`` if the string is empty after sanitisation OR if a
    prompt-injection token was detected (fail-closed). The injection is
    logged as a security event.
    """
    if value is None:
        return None
    try:
        cleaned = sanitize_for_prompt(value, max_len=max_len)
    except PromptInjectionDetected as exc:
        log.warning(
            "coach.prompt_injection_in_catalog",
            field=field,
            snippet=exc.snippet,
        )
        return None
    return cleaned or None


async def build_context(
    *,
    session: AsyncSession,
    user_id: UUID,
    conv_id: UUID,
    user_message: str,
    embedder: OpenAIEmbedder | None = None,
) -> ContextWindow:
    ctx = ContextWindow()

    # --- profile compact ---
    row = (
        await session.execute(
            text(
                """
        SELECT age, sex, goal,
               array_length(allergies, 1),
               array_length(medical_conditions, 1),
               locale
          FROM user_profiles WHERE user_id = :uid
    """
            ),
            {"uid": str(user_id)},
        )
    ).first()
    if row:
        ctx.profile_compact = (
            f"age={row[0]} sex={row[1]} goal={row[2]} "
            f"allergies_n={row[3] or 0} conditions_n={row[4] or 0} locale={row[5]}"
        )

    # --- active plan today ---
    rows = (
        await session.execute(
            text(
                """
        SELECT pm.meal_time, r.name_en, COALESCE(pm.kcal,0)
          FROM plan_meals pm
          JOIN plan_days pd ON pd.id = pm.plan_day_id
          JOIN plans p ON p.id = pd.plan_id
          LEFT JOIN recipes r ON r.id = pm.recipe_id
         WHERE p.user_id = :uid AND p.status = 'active' AND pd.date = :d
    """
            ),
            {"uid": str(user_id), "d": utc_today()},
        )
    ).all()
    if rows:
        parts: list[str] = []
        for r in rows:
            meal_name = _safe(r[1], max_len=_MEAL_NAME_MAX, field="plan_meal.name") or "—"
            parts.append(f"{r[0]}={meal_name}({r[2]}kcal)")
        ctx.active_plan_today = "; ".join(parts)

    # --- last 3 food logs ---
    rows = (
        await session.execute(
            text(
                """
        SELECT COALESCE(f.name_en, fl.free_text_name, '?'), fl.kcal
          FROM food_logs fl
          LEFT JOIN foods f ON f.id = fl.food_id
         WHERE fl.user_id = :uid
         ORDER BY fl.created_at DESC LIMIT 3
    """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    if rows:
        parts = []
        for r in rows:
            name = _safe(r[0], max_len=_FOOD_NAME_MAX, field="food_log.name") or "?"
            parts.append(f"{name}({r[1] or 0}kcal)")
        ctx.last_food_logs = "; ".join(parts)

    # --- RAG recipes top 5 ---
    if user_message.strip():
        try:
            emb = await (embedder or OpenAIEmbedder()).embed(user_message[:200])
            vec_lit = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
            # S608 noqa: vec_lit is built from floats formatted via f"{x:.6f}"
            # (no user input). pgvector requires '[..]'::vector literal form;
            # parameter binding is not supported for this operator path.
            rrows = (
                await session.execute(
                    text(
                        f"""
                SELECT name_en, kcal, protein_g
                  FROM recipes
                 WHERE embedding IS NOT NULL
                 ORDER BY embedding <=> '{vec_lit}'::vector
                 LIMIT 5
            """  # noqa: S608 — vec_lit is float-only literal; pgvector requires inline form
                    )
                )
            ).all()
            safe_rows: list[dict] = []
            for r in rrows:
                name = _safe(r[0], max_len=_RECIPE_NAME_MAX, field="recipe.name_en")
                if name is None:
                    continue  # drop the row entirely on injection
                safe_rows.append({"name_en": name, "kcal": r[1], "protein_g": r[2]})
            ctx.rag_recipes = safe_rows
        except Exception:  # noqa: BLE001
            ctx.rag_recipes = []

    # --- last 4 messages ---
    recent = await SqlConversationRepository(session).recent_messages(conv_id, limit=4)
    safe_msgs: list[dict] = []
    for m in recent:
        # Past messages are user-generated; sanitise but DON'T drop on
        # injection detection — instead replace with a placeholder so the
        # conversation history stays coherent.
        try:
            content = sanitize_for_prompt(m.content, max_len=_MESSAGE_MAX)
        except PromptInjectionDetected:
            content = "[redacted: injection attempt]"
        safe_msgs.append({"role": m.role.value, "content": content})
    ctx.last_messages = safe_msgs
    return ctx
