"""Arq task for the vision pipeline.

Memory budget: ~750 MB peak per job (pyvips already ran on the API side
during upload; here it's OpenAI + JSON parsing + food matching).
MAX_JOBS=2 keeps us under the 1.5 GB worker container limit.

Retry policy: ARQ's built-in `max_tries=3`. On terminal failure we push
to `job_deadletter` (validation #10).
"""
from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.db import get_sessionmaker, session_scope
from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.infrastructure.food_matcher import HybridFoodMatcher
from app.vision.infrastructure.openai_vision import OpenAIVisionProvider
from app.vision.infrastructure.redis_notifier import RedisJobNotifier
from app.vision.infrastructure.repositories import SqlVisionJobRepository

log = get_logger("worker.vision")

# Arq retry budget for this task (worker/main.py uses Arq's default).
# Keep in sync — used to gate terminal-failure bookkeeping below.
_MAX_TRIES = 3


async def vision_recognize_task(
    ctx: dict[str, Any],
    *,
    job_id: str,
    user_id: str,
    meal_time: str,
    image_b64: str,
    mime: str,
    locale: str = "en",
    region: str = "us",
) -> dict[str, Any]:
    image_bytes = base64.b64decode(image_b64)
    job_uuid = UUID(job_id)
    uid = UUID(user_id)
    try:
        async with session_scope() as session:
            uc = ProcessVisionJob(
                repo=SqlVisionJobRepository(session),
                provider=OpenAIVisionProvider(),
                matcher=HybridFoodMatcher(session_factory=get_sessionmaker()),
                notifier=RedisJobNotifier(),
                bus=get_event_bus(),
                session=session,
            )
            await uc(
                job_id=job_uuid, user_id=uid, meal_time=meal_time,  # type: ignore[arg-type]
                image_bytes=image_bytes, mime=mime,
                locale=locale, region=region,
            )
            return {"job_id": job_id, "status": "completed"}
    except Exception as exc:  # noqa: BLE001
        # CRITICAL: the failure bookkeeping must happen in a FRESH
        # session. The old code ran mark_failed + deadletter inside the
        # same session_scope that the re-raise then rolled back — the
        # job stayed 'running' forever and iOS polled an eternally
        # pending job. mark_failed is an idempotent UPDATE, so re-doing
        # it here after ProcessVisionJob's (rolled-back) attempt is safe.
        #
        # Terminal-attempt gating (QA 2026-06-11): Arq retries this task
        # up to MAX_TRIES times. Marking failed + deadlettering on every
        # attempt produced status whiplash (failed → running → completed)
        # for iOS polling, and up to 3 duplicate deadletter rows. Only
        # the LAST attempt records the terminal failure; earlier attempts
        # just log and let Arq retry.
        job_try = int(ctx.get("job_try") or 1)
        if job_try < _MAX_TRIES:
            log.warning(
                "vision.task.retrying",
                job_id=job_id,
                attempt=job_try,
                err=exc.__class__.__name__,
            )
            raise
        async with session_scope() as cleanup:
            await SqlVisionJobRepository(cleanup).mark_failed(
                job_uuid,
                error_code=exc.__class__.__name__,
                detail=str(exc)[:300],
            )
            await cleanup.execute(text("""
                INSERT INTO job_deadletter (task_name, args, error, attempts, failed_at)
                VALUES ('vision_recognize_task',
                        jsonb_build_object('job_id', :jid, 'user_id', :uid),
                        :err, :attempts, now())
            """), {
                "jid": job_id,
                "uid": user_id,
                "err": str(exc)[:500],
                "attempts": job_try,
            })
        raise
