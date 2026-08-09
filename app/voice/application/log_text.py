"""LogFoodText / LogFoodVoice — text or transcribed voice → food_logs.

Reuses `HybridFoodMatcher` from the vision context to resolve item names
to `food_id`. Items with no match are persisted as `free_text_name`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleViolation
from app.core.event_bus import EventBus
from app.core.redis import get_redis
from app.gamification.infrastructure.anti_cheat_caps import (
    FOOD_LOG_PER_SLOT_CAP,
    check_and_increment_food_log_slot,
)
from app.shared.domain.time import utc_today
from app.tracking.domain.events import FoodLogged
from app.vision.infrastructure.food_matcher import HybridFoodMatcher
from app.voice.infrastructure.food_text_parser import parse_food_text


@dataclass(slots=True)
class LogFoodText:
    session: AsyncSession
    matcher: HybridFoodMatcher
    bus: EventBus

    async def __call__(
        self,
        *,
        user_id: UUID,
        meal_time: Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"],
        raw_text: str,
        method: Literal["text", "voice"] = "text",
        locale: str = "es",
        idempotency_key: str | None = None,
    ) -> list[UUID]:
        items = await parse_food_text(raw_text, user_id=user_id)

        # ADR-0026 L1 — per-meal-slot cap (3 LOG EVENTS / slot / UTC day).
        # One submission = 1 against the quota, regardless of how many
        # items it parses into (fixed 2026-06-10: counting items blocked
        # legitimate multi-component meals — "arroz, pollo, ensalada y
        # palta" is ONE dinner, not four).
        if items:
            slot_count = await check_and_increment_food_log_slot(
                get_redis(),
                user_id,
                utc_today(),
                meal_time,
                amount=1,
            )
            if slot_count > FOOD_LOG_PER_SLOT_CAP:
                raise BusinessRuleViolation(
                    "meal_slot_log_cap_exceeded",
                    meal_slot=meal_time,
                    cap=FOOD_LOG_PER_SLOT_CAP,
                    current=slot_count,
                )

        food_log_ids: list[UUID] = []
        total_kcal = 0
        for it in items:
            food_id, name_norm, method_match, corrected_g = await self.matcher.match(
                name=it.name,
                amount_g=it.quantity_g,
                locale=locale,
                user_id=user_id,
            )
            # F1.1 parity: if user previously corrected this portion, apply it.
            effective_g = corrected_g if (corrected_g is not None and corrected_g > 0) else it.quantity_g
            # If matched, fetch macros per 100g and scale; else free_text only.
            kcal = protein = carbs = fat = 0
            if food_id is not None:
                row = (
                    await self.session.execute(
                        text(
                            """
                    SELECT COALESCE(kcal,0), COALESCE(protein_g,0),
                           COALESCE(carbs_g,0), COALESCE(fat_g,0)
                      FROM foods WHERE id = :fid
                """
                        ),
                        {"fid": str(food_id)},
                    )
                ).first()
                if row:
                    # CLAUDE.md non-negotiable #2 — Decimal for nutrition macro math.
                    # Scale per-100g foods by amount_g/100 with banker's rounding;
                    # only cast to int at the storage boundary.
                    factor = Decimal(str(effective_g)) / Decimal("100")

                    # Bind `factor` as default arg to silence B023 (loop closure):
                    # the call site is synchronous within the iteration, but ruff
                    # cannot prove that; explicit binding is correctness-safe.
                    def _scale(v: object, _f: Decimal = factor) -> int:
                        return int(
                            (Decimal(str(v)) * _f).quantize(
                                Decimal("1"),
                                rounding=ROUND_HALF_EVEN,
                            )
                        )

                    kcal = _scale(row[0])
                    protein = _scale(row[1])
                    carbs = _scale(row[2])
                    fat = _scale(row[3])
            flog_id = uuid4()
            await self.session.execute(
                text(
                    """
                INSERT INTO food_logs (
                    id, user_id, date, meal_time, food_id, free_text_name,
                    amount_g, kcal, protein_g, carbs_g, fat_g,
                    method, idempotency_key, created_at
                ) VALUES (
                    :id, :uid, :d, :mt, :fid, :ftn,
                    :ag, :kc, :pg, :cg, :fg,
                    :method, :idem, now()
                )
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
            """
                ),
                {
                    "id": str(flog_id),
                    "uid": str(user_id),
                    "d": utc_today(),
                    "mt": meal_time,
                    "fid": str(food_id) if food_id else None,
                    "ftn": it.name if food_id is None else None,
                    "ag": effective_g,
                    "kc": kcal,
                    "pg": protein,
                    "cg": carbs,
                    "fg": fat,
                    "method": method,
                    "idem": f"{idempotency_key}:{flog_id}" if idempotency_key else None,
                },
            )
            food_log_ids.append(flog_id)
            total_kcal += kcal

        await self.bus.publish(
            FoodLogged(
                user_id=user_id,
                meal_time=meal_time,  # type: ignore[arg-type]
                kcal=total_kcal,
                at=datetime.now(UTC),
            )
        )
        return food_log_ids
