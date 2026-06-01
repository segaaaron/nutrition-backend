"""Arq worker entry point. Bounded contexts register tasks into FUNCTIONS.

Hostinger sizing: MAX_JOBS=2 because the vision (OpenAI vision + matcher)
job peaks near 750 MB resident (pyvips runs on the API side during upload,
so the worker's per-job budget is dominated by OpenAI SDK + JSON parsing +
embedding HTTP call ≈ 700 MB). MAX_JOBS=2 keeps us under the 1.5 GB
worker container budget (spec §23).

Cron registration: all jobs use ARQ's max_tries=3 default; terminal
failures push to `job_deadletter` (validation #10).
"""
from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings
from arq import cron

from app.core.config import get_settings
from worker.coach_tasks import (
    cleanup_expired_otp_lockouts_cron,
    cleanup_expired_sse_tickets_cron,
    coach_macro_repair_cron,
    coach_proactive_alert_cron,
    coach_recipe_story_backfill_cron,
    coach_weekly_review_cron,
)
from worker.plan_tasks import generate_plan_task
from worker.vision_tasks import vision_recognize_task
from worker.idempotency_tasks import cleanup_idempotency_keys_cron

_settings = get_settings()


FUNCTIONS: list[Any] = [
    generate_plan_task,
    vision_recognize_task,
]


CRON_JOBS: list[Any] = [
    # Hourly UTC — handler filters by per-user locale offset.
    cron(coach_macro_repair_cron, name="coach_macro_repair", hour={*range(24)}, minute=5),
    cron(coach_proactive_alert_cron, name="coach_proactive_alert", hour={*range(24)}, minute=10),
    cron(coach_weekly_review_cron, name="coach_weekly_review", hour={*range(24)}, minute=15),
    # Nightly backfill — 03:00 UTC.
    cron(coach_recipe_story_backfill_cron, name="coach_recipe_story_backfill", hour={3}, minute=0),
    # Nightly cleanup — 03:00 UTC, 30-minute offset to spread I/O.
    cron(cleanup_idempotency_keys_cron, name="cleanup_idempotency_keys", hour={3}, minute=30),
    # Every 5 minutes — short-lived cleanup.
    cron(cleanup_expired_sse_tickets_cron, name="cleanup_sse_tickets", minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    cron(cleanup_expired_otp_lockouts_cron, name="cleanup_otp_lockouts", minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
]


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = _settings


async def on_shutdown(ctx: dict[str, Any]) -> None:  # noqa: ARG001
    pass


class WorkerSettings:
    functions = FUNCTIONS
    cron_jobs = CRON_JOBS
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_jobs = _settings.arq_max_jobs
    job_timeout = _settings.arq_job_timeout_seconds
    keep_result = _settings.arq_keep_result_seconds
    health_check_interval = 15
    on_startup = on_startup
    on_shutdown = on_shutdown
