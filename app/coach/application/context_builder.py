"""Build the ~600-token ContextWindow for Camino 3 grounded calls.

Sources:
  - user_profiles (compact: age, sex, goal, allergies count, conditions count).
  - active plan today (meal_time → recipe name + kcal).
  - last 3 food_logs (name + kcal).
  - top 5 recipe matches via embedding cosine on the user message.
  - last 4 conversation messages.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.coach.domain.value_objects import ContextWindow
from app.coach.infrastructure.repositories import SqlConversationRepository
from app.recipes.infrastructure.openai_embedder import OpenAIEmbedder


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
    row = (await session.execute(text("""
        SELECT age, sex, goal,
               array_length(allergies, 1),
               array_length(medical_conditions, 1),
               locale
          FROM user_profiles WHERE user_id = :uid
    """), {"uid": str(user_id)})).first()
    if row:
        ctx.profile_compact = (
            f"age={row[0]} sex={row[1]} goal={row[2]} "
            f"allergies_n={row[3] or 0} conditions_n={row[4] or 0} locale={row[5]}"
        )

    # --- active plan today ---
    rows = (await session.execute(text("""
        SELECT pm.meal_time, r.name_en, COALESCE(pm.kcal,0)
          FROM plan_meals pm
          JOIN plan_days pd ON pd.id = pm.plan_day_id
          JOIN plans p ON p.id = pd.plan_id
          LEFT JOIN recipes r ON r.id = pm.recipe_id
         WHERE p.user_id = :uid AND p.status = 'active' AND pd.date = :d
    """), {"uid": str(user_id), "d": date.today()})).all()
    if rows:
        ctx.active_plan_today = "; ".join(f"{r[0]}={r[1] or '—'}({r[2]}kcal)" for r in rows)

    # --- last 3 food logs ---
    rows = (await session.execute(text("""
        SELECT COALESCE(f.name_en, fl.free_text_name, '?'), fl.kcal
          FROM food_logs fl
          LEFT JOIN foods f ON f.id = fl.food_id
         WHERE fl.user_id = :uid
         ORDER BY fl.created_at DESC LIMIT 3
    """), {"uid": str(user_id)})).all()
    if rows:
        ctx.last_food_logs = "; ".join(f"{r[0]}({r[1] or 0}kcal)" for r in rows)

    # --- RAG recipes top 5 ---
    if user_message.strip():
        try:
            emb = await (embedder or OpenAIEmbedder()).embed(user_message[:200])
            vec_lit = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
            rrows = (await session.execute(text(f"""
                SELECT name_en, kcal, protein_g
                  FROM recipes
                 WHERE embedding IS NOT NULL
                 ORDER BY embedding <=> '{vec_lit}'::vector
                 LIMIT 5
            """))).all()
            ctx.rag_recipes = [
                {"name_en": r[0], "kcal": r[1], "protein_g": r[2]} for r in rrows
            ]
        except Exception:  # noqa: BLE001
            ctx.rag_recipes = []

    # --- last 4 messages ---
    recent = await SqlConversationRepository(session).recent_messages(conv_id, limit=4)
    ctx.last_messages = [
        {"role": m.role.value, "content": m.content} for m in recent
    ]
    return ctx
