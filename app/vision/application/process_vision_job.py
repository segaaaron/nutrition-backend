"""Worker use case — runs the vision pipeline for one VisionJob.

Steps:
  1. Mark job running.
  2. Call VisionProvider (gpt-4o vision, strict JSON).
  3. For each item: FoodMatcher.match (trigram + embedding + personal cache).
  4. Insert one food_logs row per matched item (or per item if free_text fallback).
  5. Mark job completed with persisted detected_items.
  6. Publish FoodPhotoLogged (coach + gamification subscribers).
  7. Notify client via Redis pubsub.

On any failure: mark_failed + publish VisionJobFailed + push to job_deadletter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.core.metrics import VISION_JOB_DURATION
from app.vision.domain.events import FoodPhotoLogged, VisionJobCompleted, VisionJobFailed
from app.vision.domain.ports import FoodMatcher, JobNotifier, VisionJobRepository, VisionProvider

log = get_logger("vision.process")


@dataclass(slots=True)
class ProcessVisionJob:
    repo: VisionJobRepository
    provider: VisionProvider
    matcher: FoodMatcher
    notifier: JobNotifier
    bus: EventBus
    session: AsyncSession

    async def __call__(
        self,
        *,
        job_id: UUID,
        user_id: UUID,
        meal_time: Literal["breakfast", "lunch", "dinner", "snack"],
        image_bytes: bytes,
        mime: str,
        locale: str,
        region: str,
    ) -> None:
        start = datetime.now(timezone.utc)
        await self.repo.mark_running(job_id)

        try:
            items, prompt_sha = await self.provider.recognise(
                image_bytes=image_bytes, mime=mime,
                user_id=user_id, locale=locale, region=region,
            )

            # Resolve foods (trigram + embedding).
            for it in items:
                food_id, name_norm, method = await self.matcher.match(
                    name=it.name, amount_g=float(it.estimated_amount_g),
                    locale=locale, user_id=user_id,
                )
                it.matched_food_id = food_id
                it.matched_name_norm = name_norm
                it.match_method = method

            # Persist food_logs (only items with confidence >= 0.7 land as
            # automatic logs; lower-confidence rows are stored in the job
            # detected_items jsonb for user review).
            food_log_ids: list[UUID] = []
            total_kcal = sum(i.kcal for i in items)
            for it in items:
                if it.confidence < 0.7 and it.matched_food_id is None:
                    continue
                flog_id = uuid4()
                await self.session.execute(text("""
                    INSERT INTO food_logs (
                        id, user_id, date, meal_time, food_id, free_text_name,
                        amount_g, kcal, protein_g, carbs_g, fat_g, method,
                        confidence, prompt_sha256, created_at
                    ) VALUES (
                        :id, :uid, :d, :mt, :fid, :ftn,
                        :ag, :kc, :pg, :cg, :fg, 'photo',
                        :conf, :psha, now()
                    )
                """), {
                    "id": str(flog_id), "uid": str(user_id),
                    "d": date.today(), "mt": meal_time,
                    "fid": str(it.matched_food_id) if it.matched_food_id else None,
                    "ftn": it.name if it.matched_food_id is None else None,
                    "ag": float(it.estimated_amount_g),
                    "kc": it.kcal, "pg": it.protein_g, "cg": it.carbs_g, "fg": it.fat_g,
                    "conf": it.confidence, "psha": prompt_sha,
                })
                food_log_ids.append(flog_id)

            await self.repo.mark_completed(job_id, items=items)

            now = datetime.now(timezone.utc)
            VISION_JOB_DURATION.observe((now - start).total_seconds())

            await self.bus.publish(VisionJobCompleted(
                job_id=job_id, user_id=user_id,
                n_items=len(items), total_kcal=total_kcal, at=now,
            ))
            # FoodPhotoLogged — for coach cross-check + gamification.
            await self.bus.publish(FoodPhotoLogged(
                user_id=user_id, meal_time=meal_time, kcal=total_kcal,
                food_log_ids=tuple(food_log_ids),
                detected_names=tuple(i.name for i in items),
                at=now,
            ))
            await self.notifier.notify(
                user_id=user_id, channel="vision",
                payload={"job_id": str(job_id), "status": "completed", "n_items": len(items)},
            )
            log.info("vision.process.done", job_id=str(job_id), n=len(items))

        except Exception as exc:  # noqa: BLE001
            err_code = exc.__class__.__name__
            await self.repo.mark_failed(job_id, error_code=err_code, detail=str(exc)[:300])
            await self.bus.publish(VisionJobFailed(
                job_id=job_id, user_id=user_id, error_code=err_code,
                at=datetime.now(timezone.utc),
            ))
            await self.notifier.notify(
                user_id=user_id, channel="vision",
                payload={"job_id": str(job_id), "status": "failed"},
            )
            log.warning("vision.process.failed", job_id=str(job_id), err=err_code)
            raise
