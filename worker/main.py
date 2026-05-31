"""Arq worker entry point. Bounded contexts register tasks into FUNCTIONS.

Hostinger sizing: MAX_JOBS=2 because the vision (pyvips + OpenAI) job peaks
near 750 MB resident; running > 2 concurrently OOMs the 1.5 GB worker
container budget (spec §23).
"""
from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings

_settings = get_settings()

# Tasks land here once each bounded context implements them. Keep empty
# until the corresponding context's infrastructure layer registers its tasks.
FUNCTIONS: list[Any] = []
CRON_JOBS: list[Any] = []


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
