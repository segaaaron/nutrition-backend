"""Infrastructure — persist vision-detected items as food_log rows.

Single responsibility: slot-cap guard + INSERT food_logs for every
auto-insertable item in a detected batch.

Must never be imported by the domain layer.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.gamification.infrastructure.anti_cheat_caps import (
    FOOD_LOG_PER_SLOT_CAP,
    check_and_increment_food_log_slot,
)
from app.shared.domain.time import utc_today
from app.vision.domain.entities import DetectedFoodItem

log = get_logger("vision.food_log_writer")

# Items below this confidence AND without a catalog match stay in
# detected_items JSONB for user review only — they are not auto-logged.
FOOD_LOG_AUTO_INSERT_CONFIDENCE: float = 0.7


async def persist_food_logs(
    items: list[DetectedFoodItem],
    *,
    user_id: UUID,
    meal_time: str,
    prompt_sha: str,
    session: AsyncSession,
) -> list[UUID]:
    """Slot-cap gate + INSERT food_logs for auto-insertable items.

    One photo submission = 1 slot event regardless of ingredient count.
    Inferred items (hidden oil/cream estimates) are never auto-logged.
    Returns the list of inserted food_log UUIDs.
    """
    insertable = [
        it for it in items
        if not it.inferred
        and (
            it.confidence >= FOOD_LOG_AUTO_INSERT_CONFIDENCE
            or it.matched_food_id is not None
        )
    ]
    if not insertable:
        return []

    try:
        slot_count = await check_and_increment_food_log_slot(
            get_redis(), user_id, utc_today(), meal_time, amount=1,
        )
    except Exception as rexc:  # noqa: BLE001 — OK4: Redis down must not drop the user's photo log
        log.warning("vision.slot_cap.redis_down", err=str(rexc))
        slot_count = 0

    if slot_count > FOOD_LOG_PER_SLOT_CAP:
        log.warning(
            "vision.meal_slot_log_cap_exceeded",
            extra={
                "user_id": str(user_id),
                "meal_slot": meal_time,
                "current": slot_count,
                "cap": FOOD_LOG_PER_SLOT_CAP,
            },
        )
        return []

    food_log_ids: list[UUID] = []
    for it in insertable:
        flog_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO food_logs (
                    id, user_id, date, meal_time, food_id, free_text_name,
                    amount_g, kcal, protein_g, carbs_g, fat_g, method,
                    confidence, prompt_sha256, created_at
                ) VALUES (
                    :id, :uid, :d, :mt, :fid, :ftn,
                    :ag, :kc, :pg, :cg, :fg, 'photo',
                    :conf, :psha, now()
                )
                """
            ),
            {
                "id": str(flog_id),
                "uid": str(user_id),
                "d": utc_today(),
                "mt": meal_time,
                "fid": str(it.matched_food_id) if it.matched_food_id else None,
                "ftn": it.name if it.matched_food_id is None else None,
                "ag": float(it.estimated_amount_g),
                "kc": it.kcal,
                "pg": it.protein_g,
                "cg": it.carbs_g,
                "fg": it.fat_g,
                "conf": it.confidence,
                "psha": prompt_sha,
            },
        )
        food_log_ids.append(flog_id)

    return food_log_ids
