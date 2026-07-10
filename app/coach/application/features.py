"""Coach features B / C / E / F / G — proactive coach behaviours.

  B) foto_cross_check       — on FoodPhotoLogged: compare detected vs planned
                              meal kcal. If |delta| >= 15% emit 1 hint message.
  C) macro_repair           — daily 19:00 user-locale cron. Suggests 3 snacks
                              to close the gap macros for the day.
  D) propose_swap           — see propose_swap.py (separate file).
  E) proactive_deviation    — daily 18:00. If 3-day adherence < 50% generate
                              push + coach message.
  F) recipe_story_backfill  — nightly batch. Fills recipes.coach_story_translations
                              for recipes missing a story (one mini call/recipe).
  G) weekly_review          — Sunday 18:00 user-locale. Summary message.

All use cheap gpt-4o-mini (~$0.0003/call). Cost cap applied per user via
existing pre_check. Each feature persists its output as an assistant
message in the user's active conversation (auto-create if none).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.coach.domain.entities import Message
from app.coach.domain.value_objects import Role
from app.coach.infrastructure.openai_coach_client import _get_client as _coach_client_factory
from app.coach.infrastructure.repositories import SqlConversationRepository
from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.db import session_scope
from app.core.logging import get_logger
from app.vision.application.reconcile_with_plan import ReconcileWithPlan

log = get_logger("coach.features")

_breaker_feat = CircuitBreaker(
    name="openai_coach_features", fail_threshold=3, recovery_timeout_s=30
)


async def _mini_completion(prompt: str, *, user_id: UUID | None, max_tokens: int = 150) -> str:
    model = get_settings().openai_chat_model
    est = estimate_input_cost(model, prompt) + 0.0003
    try:
        await pre_check(user_id=user_id, estimate_usd=est)
    except Exception as _cap_exc:  # noqa: BLE001
        log.info("coach.feature.cost_cap_blocked", user_id=str(user_id)[:8] if user_id else "anon", err=str(_cap_exc)[:120])
        return ""

    async def _call() -> str:
        resp = await _coach_client_factory().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content or ""
        usage = resp.usage
        await record_usage(
            user_id=user_id,
            model=model,
            in_tok=(getattr(usage, "prompt_tokens", 0) if usage else 0),
            out_tok=(getattr(usage, "completion_tokens", 0) if usage else 0),
        )
        return content

    try:
        return await _breaker_feat.call(_call)
    except Exception as exc:  # noqa: BLE001
        log.warning("coach.feature.upstream_failed", err=str(exc))
        return ""


async def _push_assistant_msg(session: AsyncSession, *, user_id: UUID, content: str) -> None:
    """Append `content` as an assistant message in the user's most recent
    active conversation (or create one)."""
    if not content.strip():
        return
    row = (
        await session.execute(
            text(
                """
        SELECT id::text FROM coach_conversations
         WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1
    """
            ),
            {"uid": str(user_id)},
        )
    ).first()
    if row:
        conv_id = UUID(row[0])
    else:
        repo = SqlConversationRepository(session)
        conv = await repo.get_or_create(user_id, None)
        conv_id = conv.id
    repo = SqlConversationRepository(session)
    await repo.append_message(
        Message(
            conv_id=conv_id,
            role=Role.ASSISTANT,
            content=content,
            created_at=datetime.now(UTC),
        )
    )


# ---------------------------------------------------------------------------
# Feature B — photo cross-check
# ---------------------------------------------------------------------------


async def foto_cross_check(
    session: AsyncSession,
    *,
    user_id: UUID,
    meal_time: str,
    detected_kcal: int,
    detected_names: tuple[str, ...],
) -> None:
    reconcile = ReconcileWithPlan(session=session)
    report = await reconcile(user_id=user_id, meal_time=meal_time, detected_kcal=detected_kcal)
    if not report or not report["needs_hint"]:
        return
    delta_pct = report["delta_pct"]
    direction = "más" if delta_pct > 0 else "menos"
    prompt = (
        f"El usuario comió ~{detected_kcal} kcal en {meal_time} pero su plan "
        f"esperaba {report['planned_kcal']} kcal ({direction} {abs(int(delta_pct*100))}%). "
        f"Da una sola frase coach, práctica, sin diagnóstico médico."
    )
    msg = await _mini_completion(prompt, user_id=user_id, max_tokens=80)
    if msg:
        await _push_assistant_msg(session, user_id=user_id, content=msg)


# ---------------------------------------------------------------------------
# Feature C — macro repair (cron 19:00 user-locale)
# ---------------------------------------------------------------------------


async def macro_repair(session: AsyncSession, *, user_id: UUID) -> None:
    goal_row = (
        await session.execute(
            text(
                """
        SELECT kcal_min, kcal_max, protein_g, carbs_g, fat_g
          FROM nutritional_goals WHERE user_id = :uid AND valid_to IS NULL
    """
            ),
            {"uid": str(user_id)},
        )
    ).first()
    if not goal_row:
        return
    intake = (
        await session.execute(
            text(
                """
        SELECT COALESCE(SUM(kcal),0)::int, COALESCE(SUM(protein_g),0)::int,
               COALESCE(SUM(carbs_g),0)::int, COALESCE(SUM(fat_g),0)::int
          FROM food_logs WHERE user_id = :uid AND date = CURRENT_DATE
    """
            ),
            {"uid": str(user_id)},
        )
    ).first()
    kcal_gap = int(goal_row[0]) - int(intake[0])
    protein_gap = int(goal_row[2]) - int(intake[1])
    if kcal_gap < 100 and protein_gap < 5:
        return  # already on track
    # Pick 3 snack candidates ranked by protein-density that fit the gap.
    snacks = (
        await session.execute(
            text(
                """
        SELECT name_en, kcal, protein_g
          FROM recipes
         WHERE meal_time = 'snack' AND kcal IS NOT NULL
           AND kcal <= :kgap
         ORDER BY (CASE WHEN kcal>0 THEN protein_g::float / kcal ELSE 0 END) DESC
         LIMIT 3
    """
            ),
            {"kgap": max(120, kcal_gap)},
        )
    ).all()
    if not snacks:
        return
    snack_str = "; ".join(f"{r[0]} ({r[1]}kcal/{r[2]}p)" for r in snacks)
    prompt = (
        f"Faltan {kcal_gap} kcal y {protein_gap}g proteína hoy. Sugiere uno de "
        f"estos snacks en una frase: {snack_str}"
    )
    msg = await _mini_completion(prompt, user_id=user_id, max_tokens=80)
    if msg:
        await _push_assistant_msg(session, user_id=user_id, content=msg)


# ---------------------------------------------------------------------------
# Feature E — proactive deviation alert
# ---------------------------------------------------------------------------


async def proactive_deviation(session: AsyncSession, *, user_id: UUID) -> dict | None:
    """Returns push payload if alert sent, else None."""
    row = (
        (
            await session.execute(
                text(
                    """
        SELECT COUNT(*) FROM plan_meals pm
          JOIN plan_days pd ON pd.id = pm.plan_day_id
          JOIN plans p ON p.id = pd.plan_id
         WHERE p.user_id = :uid AND p.status = 'active'
           AND pd.date BETWEEN CURRENT_DATE - INTERVAL '2 days' AND CURRENT_DATE
    """
                ),
                {"uid": str(user_id)},
            )
        ).scalar()
        or 0
    )
    if row == 0:
        return None
    completed = (
        (
            await session.execute(
                text(
                    """
        SELECT COUNT(*) FROM plan_meals pm
          JOIN plan_days pd ON pd.id = pm.plan_day_id
          JOIN plans p ON p.id = pd.plan_id
         WHERE p.user_id = :uid AND p.status = 'active'
           AND pd.date BETWEEN CURRENT_DATE - INTERVAL '2 days' AND CURRENT_DATE
           AND pm.completed = true
    """
                ),
                {"uid": str(user_id)},
            )
        ).scalar()
        or 0
    )
    adherence = completed / row
    if adherence >= 0.5:
        return None
    prompt = (
        f"El usuario tiene adherencia {int(adherence*100)}% en 3 días. "
        f"En una frase coach, motívalo a retomar el plan sin culpa."
    )
    msg = await _mini_completion(prompt, user_id=user_id, max_tokens=80)
    if not msg:
        return None
    await _push_assistant_msg(session, user_id=user_id, content=msg)
    return {"title": "NOVA Coach", "body": msg[:140]}


# ---------------------------------------------------------------------------
# Feature F — recipe story backfill (nightly batch)
# ---------------------------------------------------------------------------


async def recipe_story_backfill(session: AsyncSession, *, batch: int = 20) -> int:
    rows = (
        await session.execute(
            text(
                """
        SELECT id::text, name_en, description_en
          FROM recipes
         WHERE coach_story_translations = '{}'::jsonb
            OR coach_story_translations IS NULL
         ORDER BY created_at ASC LIMIT :n
    """
            ),
            {"n": batch},
        )
    ).all()
    n_done = 0
    for r in rows:
        prompt = (
            f"En una frase, cuenta el 'porqué' nutricional de la receta "
            f"\"{r[1]}\" ({r[2] or 'sin descripción'}). Estilo coach, "
            f"~25 palabras."
        )
        msg = await _mini_completion(prompt, user_id=None, max_tokens=60)
        if not msg:
            continue
        # Open a fresh session per recipe so each UPDATE is committed
        # independently.  A failure (or exception) in one iteration does NOT
        # roll back the stories already written for earlier recipes.
        try:
            async with session_scope() as inner:
                await inner.execute(
                    text(
                        """
                UPDATE recipes
                   SET coach_story_translations = jsonb_build_object('es', :es, 'en', :en)
                 WHERE id = :id
            """
                    ),
                    {"id": r[0], "es": msg, "en": msg},
                )
            n_done += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("recipe_story.update_failed", recipe_id=r[0], err=str(exc))
    return n_done


# ---------------------------------------------------------------------------
# Feature G — weekly review (Sunday 18:00 user-locale)
# ---------------------------------------------------------------------------


async def weekly_review(session: AsyncSession, *, user_id: UUID) -> None:
    summary = (
        await session.execute(
            text(
                """
        SELECT
          COUNT(DISTINCT date) AS active_days,
          COALESCE(AVG(kcal_day),0)::int AS avg_kcal,
          COALESCE(AVG(prot_day),0)::int AS avg_prot
        FROM (
          SELECT date,
                 SUM(kcal) AS kcal_day,
                 SUM(protein_g) AS prot_day
            FROM food_logs
           WHERE user_id = :uid AND date >= CURRENT_DATE - INTERVAL '7 days'
           GROUP BY date
        ) x
    """
            ),
            {"uid": str(user_id)},
        )
    ).first()
    if not summary or not summary[0]:
        return
    prompt = (
        f"Resumen semanal del usuario: {summary[0]}/7 días con logs, "
        f"promedio {summary[1]} kcal y {summary[2]}g proteína. "
        f"Da 2-3 líneas coach amables, sin diagnóstico médico."
    )
    msg = await _mini_completion(prompt, user_id=user_id, max_tokens=150)
    if msg:
        await _push_assistant_msg(session, user_id=user_id, content=msg)
