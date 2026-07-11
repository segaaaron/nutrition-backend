"""Arq enqueuer for `generate_plan_task`.

Centralised here so `POST /plans` enqueues plan generation jobs with
consistent semantics (`_job_id` naming, `plan_type` defaults, locale
propagation). Pure infrastructure — no business decisions live here.

`enqueue_and_wait_plan` blocks on the worker result so the request can
return `status="ready"` synchronously (BE-7). It distinguishes two very
different "no plan yet" cases:
  - the wait TIMED OUT (worker slow / still retrying) → `(job_id, None)`,
    caller returns 202 "queued" and the client polls;
  - the worker TERMINALLY FAILED (retries exhausted) → raises
    ``PlanGenerationFailed`` (503) so the client shows an error instead of
    spinning forever on a "queued" that will never resolve.
Masking a terminal failure as "queued" was the BE-7 gap iOS hit 2026-07-11
("no error, just no plan ever appears").
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq.connections import RedisSettings, create_pool

from app.core.config import get_settings
from app.core.errors import PlanGenerationFailed


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
    the worker completes within ``wait_timeout``. ``(job_id, None)`` means the
    wait TIMED OUT (worker slow / still retrying) — the caller returns 202
    "queued" and the client polls. A TERMINAL worker failure (task raised after
    its retries) raises ``PlanGenerationFailed`` (503) so the client shows an
    error rather than a "queued" that never resolves.
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
        except TimeoutError:
            # Worker still running/retrying past the wait window → async
            # fallback (202 queued). NOT a failure — the plan may still land.
            return job.job_id, None
        except Exception as exc:  # noqa: BLE001 — worker raised a terminal failure
            # Retries exhausted / task errored. Surface it — never mask as
            # "queued" (that leaves the client spinning forever, no error).
            raise PlanGenerationFailed(str(exc)[:200]) from exc
        plan_id = result.get("plan_id") if isinstance(result, dict) else None
        return job.job_id, plan_id
    finally:
        await pool.close()
