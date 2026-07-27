"""ADR-0026 L1 slot cap counts LOG EVENTS, not detected ingredients.

Regression for 2026-06-10 prod incident: a single dinner photo detected 8
ingredients; the worker incremented the per-slot counter by 8 (> cap 3) and
dropped ALL food_logs inserts — the user's meal logged nothing and the slot
quota was burned for the rest of the day. One photo submission must count
as exactly 1 against the quota and insert every eligible item.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import app.vision.infrastructure.food_log_writer as food_log_writer_mod
from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.domain.entities import DetectedFoodItem, VisionJob


def _items(n: int) -> list[DetectedFoodItem]:
    return [
        DetectedFoodItem(
            name=f"ingrediente {i}",
            estimated_amount_g=Decimal("50"),
            kcal=100,
            protein_g=5,
            carbs_g=10,
            fat_g=3,
            confidence=0.9,  # all above FOOD_LOG_AUTO_INSERT_CONFIDENCE
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_one_photo_with_8_items_counts_1_event_and_inserts_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("VISION_TWO_PASS_ENABLED", "false")
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "false")
    get_settings.cache_clear()

    job_id = uuid4()
    user_id = uuid4()

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.mark_failed = AsyncMock()
    repo.get = AsyncMock(
        return_value=VisionJob(
            id=job_id,
            user_id=user_id,
            image_sha256="e" * 64,
            status="running",
            created_at=datetime.now(UTC),
        )
    )
    repo.find_recent_completed_by_sha = AsyncMock(return_value=None)

    provider = MagicMock()
    provider.current_prompt_sha256 = MagicMock(return_value="sha-test")
    provider.recognise = AsyncMock(return_value=(_items(8), "sha-test"))

    matcher = MagicMock()
    matcher.match = AsyncMock(return_value=(None, None, "unmatched", None))

    session = MagicMock()
    session.execute = AsyncMock()
    notifier = MagicMock()
    notifier.notify = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    captured: dict[str, object] = {}

    async def _fake_slot_counter(redis, uid, on, meal_slot, amount=1):  # noqa: ANN001
        captured["amount"] = amount
        captured["meal_slot"] = meal_slot
        return amount  # first event of the day: post-increment == amount

    monkeypatch.setattr(
        food_log_writer_mod, "check_and_increment_food_log_slot", _fake_slot_counter
    )

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
        meal_time="dinner",
        image_bytes=b"fake-image",
        mime="image/jpeg",
        locale="es",
        region="latam",
    )

    # One photo = ONE event against the slot quota.
    assert captured["amount"] == 1
    assert captured["meal_slot"] == "dinner"
    # All 8 eligible items inserted as food_logs rows.
    insert_calls = [
        c for c in session.execute.await_args_list
        if "INSERT INTO food_logs" in str(c.args[0])
    ]
    assert len(insert_calls) == 8
    repo.mark_completed.assert_awaited_once()
