"""BE-7 — `enqueue_and_wait_plan` timeout-vs-terminal-failure contract.

The synchronous `POST /plans` must NOT mask a terminal worker failure as
"queued": that leaves the client spinning forever with no error (the bug iOS
hit 2026-07-11). A timeout is "still working" (202 queued); a raised worker
task is a failure (503 `plan_generation_failed`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from app.core.errors import PlanGenerationFailed
from app.plan.infrastructure import plan_enqueuer

USER = UUID("22222222-2222-2222-2222-222222222222")


class _FakeJob:
    job_id = "arq-job-1"

    def __init__(self, *, result: Any = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    async def result(self, timeout: float) -> Any:  # noqa: ASYNC109 — mirrors arq Job.result(timeout=)
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakePool:
    def __init__(self, job: _FakeJob | None) -> None:
        self._job = job

    async def enqueue_job(self, *_a: Any, **_kw: Any) -> _FakeJob | None:
        return self._job

    async def close(self) -> None:
        return None


def _patch_pool(monkeypatch: pytest.MonkeyPatch, job: _FakeJob | None) -> None:
    async def _create_pool(*_a: Any, **_kw: Any) -> _FakePool:
        return _FakePool(job)

    monkeypatch.setattr(plan_enqueuer, "create_pool", _create_pool)


async def _call() -> tuple[str | None, str | None]:
    return await plan_enqueuer.enqueue_and_wait_plan(
        user_id=USER, plan_type="week", job_id=f"plan:{USER}:key", wait_timeout=1.0
    )


@pytest.mark.asyncio
async def test_ready_returns_plan_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pool(monkeypatch, _FakeJob(result={"plan_id": "the-plan"}))
    job_id, plan_id = await _call()
    assert job_id == "arq-job-1"
    assert plan_id == "the-plan"


@pytest.mark.asyncio
async def test_timeout_degrades_to_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wait timed out → (job_id, None) so the caller returns 202 "queued".
    _patch_pool(monkeypatch, _FakeJob(exc=TimeoutError()))
    job_id, plan_id = await _call()
    assert job_id == "arq-job-1"
    assert plan_id is None


@pytest.mark.asyncio
async def test_terminal_worker_failure_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    # Worker task raised (retries exhausted) → surface, never mask as queued.
    _patch_pool(monkeypatch, _FakeJob(exc=RuntimeError("IllegalStateChangeError")))
    with pytest.raises(PlanGenerationFailed) as ei:
        await _call()
    assert ei.value.http_status == 503
    assert ei.value.type_slug == "plan_generation_failed"


@pytest.mark.asyncio
async def test_broker_declined_returns_none_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pool(monkeypatch, None)  # enqueue_job returned None
    job_id, plan_id = await _call()
    assert job_id is None
    assert plan_id is None
