"""LogFoodText / LogFoodVoice — text or transcribed voice → food_logs.

Reuses `HybridFoodMatcher` from the vision context to resolve item names
to `food_id`. Items with no match are persisted as `free_text_name`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import EventBus
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
        meal_time: Literal["breakfast", "lunch", "dinner", "snack"],
        raw_text: str,
        method: Literal["text", "voice"] = "text",
        locale: str = "es",
        idempotency_key: str | None = None,
    ) -> list[UUID]:
        items = await parse_food_text(raw_text, user_id=user_id)
        food_log_ids: list[UUID] = []
        total_kcal = 0
        for it in items:
            food_id, name_norm, method_match = await self.matcher.match(
                name=it.name, amount_g=it.quantity_g, locale=locale, user_id=user_id,
            )
            # If matched, fetch macros per 100g and scale; else free_text only.
            kcal = protein = carbs = fat = 0
            if food_id is not None:
                row = (await self.session.execute(text("""
                    SELECT COALESCE(kcal,0), COALESCE(protein_g,0),
                           COALESCE(carbs_g,0), COALESCE(fat_g,0)
                      FROM foods WHERE id = :fid
                """), {"fid": str(food_id)})).first()
                if row:
                    factor = it.quantity_g / 100.0
                    kcal = int(float(row[0]) * factor)
                    protein = int(float(row[1]) * factor)
                    carbs = int(float(row[2]) * factor)
                    fat = int(float(row[3]) * factor)
            flog_id = uuid4()
            await self.session.execute(text("""
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
            """), {
                "id": str(flog_id), "uid": str(user_id),
                "d": date.today(), "mt": meal_time,
                "fid": str(food_id) if food_id else None,
                "ftn": it.name if food_id is None else None,
                "ag": it.quantity_g,
                "kc": kcal, "pg": protein, "cg": carbs, "fg": fat,
                "method": method,
                "idem": f"{idempotency_key}:{flog_id}" if idempotency_key else None,
            })
            food_log_ids.append(flog_id)
            total_kcal += kcal

        await self.bus.publish(FoodLogged(
            user_id=user_id, meal_time=meal_time,  # type: ignore[arg-type]
            kcal=total_kcal, at=datetime.now(timezone.utc),
        ))
        return food_log_ids
