"""Arq enqueuer for `generate_plan_task`.

Centralised here so both `POST /plans` and `POST /me/onboarding` enqueue
plan generation jobs with identical semantics (`_job_id` naming,
`plan_type` defaults, locale propagation). Pure infrastructure — no
business decisions live here.

The function returns the assigned `job_id` (Arq's deterministic
deduplication ID when `_job_id` is supplied), or `None` if the broker
declined to schedule the job (e.g., a same-key job is already in flight).
Callers that depend on Redis availability must catch broker errors
themselves; we only translate "no job scheduled" into `None`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq.connections import RedisSettings, create_pool

from app.core.config import get_settings


async def enqueue_generate_plan(
    *,
    user_id: UUID,
    plan_type: str,
    preferences: list[str] | None = None,
    seed: int | None = None,
    locale: str | None = None,
    job_id: str,
) -> str | None:
    """Enqueue `generate_plan_task` on the Arq Redis pool.

    `job_id` is passed to Arq as `_job_id` to give callers idempotent
    enqueue semantics (replays with the same id are deduplicated by
    Arq itself for a configurable window).
    """
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job: Any = await pool.enqueue_job(
            "generate_plan_task",
            user_id=str(user_id),
            plan_type=plan_type,
            preferences=preferences,
            seed=seed,
            locale=locale,
            _job_id=job_id,
        )
    finally:
        await pool.close()
    if job is None:
        return None
    return job.job_id
