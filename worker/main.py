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

# Pre-register every ORM model with ``Base.metadata`` so cross-table
# ForeignKey strings (e.g. plan_meals.recipe_id → recipes.id) resolve
# regardless of which use case the worker dispatches first. Without this
# the first generate_plan_task fails with NoReferencedTableError because
# only the plan models are imported transitively.
import app.coach.infrastructure.models  # noqa: F401
import app.identity.infrastructure.models  # noqa: F401
import app.notifications.infrastructure.models  # noqa: F401
import app.nutrition.infrastructure.models  # noqa: F401
import app.plan.infrastructure.models  # noqa: F401
import app.profile.infrastructure.models  # noqa: F401
import app.recipes.infrastructure.models  # noqa: F401
import app.tracking.infrastructure.models  # noqa: F401
import app.vision.infrastructure.models  # noqa: F401
from app.core.config import get_settings
from worker.email_tasks import send_email_task
from worker.outbox_listener import start_outbox_listener, stop_outbox_listener
from worker.plan_tasks import generate_plan_task
from worker.vision_tasks import vision_recognize_task

_settings = get_settings()


FUNCTIONS: list[Any] = [
    generate_plan_task,
    vision_recognize_task,
    send_email_task,
]


CRON_JOBS: list[Any] = []
# No crons at pre-production stage — zero users means zero work to do.
# Crons running with empty tables waste RAM, DB connections, and VPS resources.
#
# Re-enable when real users exist:
#   outbox_drainer   → replace with PostgreSQL LISTEN/NOTIFY (no polling)
#   nightly_maintenance → replace with pg_cron extension (runs inside DB, zero app overhead)


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = _settings
    # ADR-0028 — register profile-side PlanCreated subscriber inside the
    # worker process. EventBus is an in-process singleton so the API's
    # registration does NOT cover plan generation jobs that run here.
    from app.core.db import get_sessionmaker
    from app.core.event_bus import get_event_bus
    from app.profile.application.event_handlers import (
        register as register_profile_handlers,
    )

    register_profile_handlers(get_event_bus(), get_sessionmaker())
    # Outbox LISTEN/NOTIFY — zero-latency event replay, no polling cron needed.
    await start_outbox_listener(ctx)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await stop_outbox_listener(ctx)


class WorkerSettings:
    functions = FUNCTIONS
    cron_jobs = CRON_JOBS
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_jobs = _settings.arq_max_jobs
    job_timeout = _settings.arq_job_timeout_seconds
    keep_result = _settings.arq_keep_result_seconds
    max_tries = 3  # Arq default is 5; vision/plan tasks guard on _MAX_TRIES=3 so mismatching left jobs in running state forever
    health_check_interval = 15
    on_startup = on_startup
    on_shutdown = on_shutdown
