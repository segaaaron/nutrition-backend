"""Unit — HIGH-2 fix: concurrent workers processing the same SHA must
serialise through the Redis in-flight lock so the provider is only called
once. The losing worker should wait on the cache and reuse the result.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.application import process_vision_job as pvj_mod
from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.domain.entities import DetectedFoodItem, VisionJob


def _det(name: str = "x") -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal("10"),
        kcal=5,
        protein_g=0,
        carbs_g=1,
        fat_g=0,
        confidence=0.95,
    )


@pytest.mark.asyncio
async def test_concurrent_same_sha_provider_called_once(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    # Shrink the inflight poll budget so the test doesn't hang.
    monkeypatch.setattr(pvj_mod, "_INFLIGHT_WAIT_S", 5)
    monkeypatch.setattr(pvj_mod, "get_redis", lambda: fake_redis)

    sha = "d" * 64
    user = uuid4()
    job_a = uuid4()
    job_b = uuid4()

    # Shared cache: starts empty; populated only after winner completes.
    cache_storage: dict[str, list[DetectedFoodItem]] = {}

    async def find_recent(
        *, image_sha256: str, ttl_days: int, current_prompt_sha256: str | None = None
    ):
        items = cache_storage.get(image_sha256)
        if items is None:
            return None
        return list(items), "shared-prompt-sha"

    def _mk_repo(jid: str):
        r = MagicMock()
        r.mark_running = AsyncMock()
        r.mark_completed = AsyncMock()
        r.mark_failed = AsyncMock()
        r.get = AsyncMock(
            return_value=VisionJob(
                id=jid,
                user_id=user,
                image_sha256=sha,
                status="running",
                created_at=datetime.now(UTC),
            )
        )
        r.find_recent_completed_by_sha = AsyncMock(side_effect=find_recent)
        return r

    # Provider: called only by the winner. We add an artificial delay so
    # the loser definitely starts before the winner finishes.
    provider_call_count = 0

    async def recognise(**_kw):
        nonlocal provider_call_count
        provider_call_count += 1
        await asyncio.sleep(0.3)
        items = [_det("avena")]
        cache_storage[sha] = items
        return items, "shared-prompt-sha"

    provider = MagicMock()
    provider.recognise = AsyncMock(side_effect=recognise)

    matcher = MagicMock()
    matcher.match = AsyncMock(return_value=(uuid4(), "x", "trigram"))

    notifier = MagicMock()
    notifier.notify = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    def _mk_uc(jid):
        return ProcessVisionJob(
            repo=_mk_repo(jid),
            provider=provider,
            matcher=matcher,
            notifier=notifier,
            bus=bus,
            session=MagicMock(execute=AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        )

    uc_a = _mk_uc(job_a)
    uc_b = _mk_uc(job_b)

    async def _run(uc, jid):
        await uc(
            job_id=jid,
            user_id=user,
            meal_time="lunch",
            image_bytes=b"i",
            mime="image/jpeg",
            locale="es",
            region="latam",
        )

    await asyncio.gather(_run(uc_a, job_a), _run(uc_b, job_b))

    assert (
        provider_call_count == 1
    ), f"provider invoked {provider_call_count}x; lock did not serialise"
