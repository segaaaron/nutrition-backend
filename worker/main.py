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

from arq import cron
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
from worker.anomaly_score_task import anomaly_score_task
from worker.coach_tasks import (
    cleanup_expired_otp_lockouts_cron,
    cleanup_expired_sse_tickets_cron,
    coach_macro_repair_cron,
    coach_proactive_alert_cron,
    coach_recipe_story_backfill_cron,
    coach_weekly_review_cron,
)
from worker.email_tasks import send_email_task
from worker.idempotency_tasks import cleanup_idempotency_keys_cron
from worker.leaderboard_audit_purge_task import leaderboard_audit_purge_cron
from worker.outbox_drainer import outbox_drainer_cron
from worker.plan_tasks import generate_plan_task
from worker.vision_tasks import vision_recognize_task

_settings = get_settings()


FUNCTIONS: list[Any] = [
    generate_plan_task,
    vision_recognize_task,
    send_email_task,
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
    # ADR-0026 — anti-cheat audit retention purge (180-day horizon).
    # 03:00 UTC = 22:00 Lima previous day.
    cron(leaderboard_audit_purge_cron, name="leaderboard_audit_purge", hour={3}, minute=0),
    # ADR-0026 L2 — nightly anomaly scorer. 02:00 Lima = 07:00 UTC
    # (Peru is UTC-5 year-round; no DST). arq's cron() runs in the
    # worker process timezone which is UTC inside the container, so we
    # schedule UTC directly. L3 ZADD gate deferred (see PROJECT_STATE.md).
    # Threshold actions: >=70 ban, 40-69 flag, <40 ok.
    cron(anomaly_score_task, name="anomaly_score", hour={7}, minute=0),
    # Every 5 minutes — short-lived cleanup.
    cron(cleanup_expired_sse_tickets_cron, name="cleanup_sse_tickets", minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    cron(cleanup_expired_otp_lockouts_cron, name="cleanup_otp_lockouts", minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    # ADR-0030 — outbox retry cadence (every minute). Picks up domain
    # events whose post-commit handler raised, logs + bumps attempts.
    cron(outbox_drainer_cron, name="outbox_drainer", minute=set(range(60))),
]


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
