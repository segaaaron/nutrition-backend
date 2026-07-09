"""Unit — SHA256 dedup cache short-circuits the LLM provider call.

Covers Capa 1 of the cost-cascade strategy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.domain.entities import DetectedFoodItem, VisionJob


def _item(name: str = "avena", conf: float = 0.9) -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal("60"),
        kcal=230,
        protein_g=7,
        carbs_g=40,
        fat_g=4,
        confidence=conf,
        matched_food_id=uuid4(),  # pre-matched so food_logs insert path runs
        matched_name_norm=name,
        match_method="trigram",
    )


@pytest.mark.asyncio
async def test_cache_hit_skips_provider() -> None:
    job_id = uuid4()
    user_id = uuid4()
    sha = "a" * 64

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.mark_failed = AsyncMock()
    repo.get = AsyncMock(
        return_value=VisionJob(
            id=job_id,
            user_id=user_id,
            image_sha256=sha,
            status="running",
            created_at=datetime.now(UTC),
        )
    )
    cached = [_item("avena"), _item("platano")]
    repo.find_recent_completed_by_sha = AsyncMock(return_value=cached)

    provider = MagicMock()
    provider.recognise = AsyncMock()  # must NOT be called

    matcher = MagicMock()
    matcher.match = AsyncMock(return_value=(uuid4(), "avena", "trigram", None))

    session = MagicMock()
    _exec_result = MagicMock()
    _exec_result.all.return_value = []
    session.execute = AsyncMock(return_value=_exec_result)

    notifier = MagicMock()
    notifier.notify = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    uc = ProcessVisionJob(
        repo=repo,
        provider=provider,
        matcher=matcher,
        notifier=notifier,
        bus=bus,
        session=session,
    )

    await uc(
        job_id=job_id,
        user_id=user_id,
        meal_time="lunch",
        image_bytes=b"ignored-on-cache-hit",
        mime="image/jpeg",
        locale="es",
        region="latam",
    )

    provider.recognise.assert_not_called()
    repo.find_recent_completed_by_sha.assert_awaited_once()
    repo.mark_completed.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_miss_calls_provider() -> None:
    job_id = uuid4()
    user_id = uuid4()
    sha = "b" * 64

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.mark_failed = AsyncMock()
    repo.get = AsyncMock(
        return_value=VisionJob(
            id=job_id,
            user_id=user_id,
            image_sha256=sha,
            status="running",
            created_at=datetime.now(UTC),
        )
    )
    repo.find_recent_completed_by_sha = AsyncMock(return_value=None)

    fresh = [_item("manzana", conf=0.95)]
    provider = MagicMock()
    provider.recognise = AsyncMock(return_value=(fresh, "promptsha123"))

    matcher = MagicMock()
    matcher.match = AsyncMock(return_value=(uuid4(), "manzana", "trigram", None))

    session = MagicMock()
    _exec_result = MagicMock()
    _exec_result.all.return_value = []
    session.execute = AsyncMock(return_value=_exec_result)

    notifier = MagicMock()
    notifier.notify = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    uc = ProcessVisionJob(
        repo=repo,
        provider=provider,
        matcher=matcher,
        notifier=notifier,
        bus=bus,
        session=session,
    )

    await uc(
        job_id=job_id,
        user_id=user_id,
        meal_time="snack",
        image_bytes=b"some-image",
        mime="image/jpeg",
        locale="es",
        region="latam",
    )

    provider.recognise.assert_awaited_once()
    repo.mark_completed.assert_awaited_once()
