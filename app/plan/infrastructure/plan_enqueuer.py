"""Arq enqueuer for `generate_plan_task`.

Centralised here so `POST /plans` enqueues plan generation jobs with
consistent semantics (`_job_id` naming, `plan_type` defaults, locale
propagation). Pure infrastructure — no business decisions live here.

`enqueue_and_wait_plan` blocks on the worker result so the request can
return `status="ready"` synchronously (BE-7); it degrades to the async
`(job_id, None)` on timeout/broker decline so the caller falls back to
the 202 + client-poll path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq.connections import RedisSettings, create_pool

from app.core.config import get_settings


async def enqueue_and_wait_plan(
    *,
    user_id: UUID,
    plan_type: str,
    preferences: list[str] | None = None,
    seed: int | None = None,
    locale: str | None = None,
    job_id: str,
    wait_timeout: float = 25.0,
) -> tuple[str | None, str | None]:
    """Enqueue plan generation and BLOCK until the worker finishes (BE-7).

    Returns ``(job_id, plan_id)``. ``plan_id`` is the generated plan's id when
    the worker completes within ``wait_timeout``; ``None`` if the wait times
    out (caller falls back to the async 202 + client poll) or the broker
    declined the job. Keeps the request tied to the real completion so iOS
    never has to poll with timers.
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
        if job is None:
            return None, None
        try:
            result: Any = await job.result(timeout=wait_timeout)
        except Exception:  # noqa: BLE001 — any wait failure (timeout, worker error) → async fallback
            return job.job_id, None
        plan_id = result.get("plan_id") if isinstance(result, dict) else None
        return job.job_id, plan_id
    finally:
        await pool.close()
