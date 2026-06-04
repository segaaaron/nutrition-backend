"""Integration — VisionJobRepository round-trip against real Postgres.

Validates:
- save() persists, get() returns equivalent entity
- mark_running, mark_completed, mark_failed transition status correctly
- detected_items JSONB roundtrips through pg without value drift
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.vision.domain.entities import DetectedFoodItem, VisionJob
from app.vision.infrastructure.repositories import SqlVisionJobRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_save_then_get_roundtrip(db_session: Any, fake_user_id: UUID) -> None:
    repo = SqlVisionJobRepository(db_session)
    job = VisionJob(
        id=uuid4(),
        user_id=fake_user_id,
        meal_time="lunch",
        status="queued",
        image_sha256="a" * 64,
        image_bytes=2048,
        idempotency_key="idem-rt-1",
        prompt_sha256=None,
        created_at=datetime.now(UTC),
    )
    await repo.save(job)
    await db_session.commit()

    fetched = await repo.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.user_id == fake_user_id
    assert fetched.status == "queued"
    assert fetched.image_sha256 == "a" * 64
    assert fetched.idempotency_key == "idem-rt-1"


@pytest.mark.asyncio
async def test_status_transitions_running_completed(
    db_session: Any,
    fake_user_id: UUID,
) -> None:
    repo = SqlVisionJobRepository(db_session)
    job = VisionJob(
        id=uuid4(),
        user_id=fake_user_id,
        image_sha256="b" * 64,
        image_bytes=100,
        status="queued",
        created_at=datetime.now(UTC),
    )
    await repo.save(job)
    await repo.mark_running(job.id)
    await db_session.commit()

    running = await repo.get(job.id)
    assert running is not None
    assert running.status == "running"
    assert running.started_at is not None

    items = [
        DetectedFoodItem(
            name="rice",
            estimated_amount_g=Decimal("100"),
            kcal=130,
            protein_g=2,
            carbs_g=28,
            fat_g=0,
            confidence=0.9,
        )
    ]
    await repo.mark_completed(job.id, items=items)
    await db_session.commit()

    done = await repo.get(job.id)
    assert done is not None
    assert done.status == "completed"
    assert done.completed_at is not None
    assert len(done.detected_items) == 1
    assert done.detected_items[0].name == "rice"


@pytest.mark.asyncio
async def test_mark_failed_caps_detail(db_session: Any, fake_user_id: UUID) -> None:
    repo = SqlVisionJobRepository(db_session)
    job = VisionJob(
        id=uuid4(),
        user_id=fake_user_id,
        image_sha256="c" * 64,
        image_bytes=50,
        status="queued",
        created_at=datetime.now(UTC),
    )
    await repo.save(job)
    await repo.mark_failed(job.id, error_code="ProviderError", detail="x" * 9999)
    await db_session.commit()

    failed = await repo.get(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "ProviderError"
    # PII / log-storage cap: error_detail truncated to 500 chars at the repo.
    assert failed.error_detail is not None
    assert len(failed.error_detail) <= 500
