"""Unit — servings feature.

Covers:
- food_log_writer.persist_food_logs divides amounts/macros by servings.
- servings=1 (default) → no division (values unchanged).
- servings=0 guard → treated as 1 (no divide-by-zero).
- VisionJob stores servings clamped 1..8.
- submit_photo clamps servings to 1..8.
"""
from __future__ import annotations

import math
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.vision.domain.entities import DetectedFoodItem, VisionJob
from app.vision.application.submit_photo import SubmitPhoto


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(
    *,
    kcal: int = 400,
    protein_g: int = 30,
    carbs_g: int = 40,
    fat_g: int = 10,
    fiber_g: int = 4,
    sugar_g: int = 6,
    amount_g: float = 200.0,
    confidence: float = 0.9,
) -> DetectedFoodItem:
    return DetectedFoodItem(
        name="pollo con arroz",
        estimated_amount_g=Decimal(str(amount_g)),
        kcal=kcal,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        fiber_g=fiber_g,
        sugar_g=sugar_g,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# food_log_writer — division by servings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_food_logs_servings_1_no_division() -> None:
    """servings=1: amounts written unchanged."""
    from app.vision.infrastructure.food_log_writer import persist_food_logs

    session = AsyncMock()
    session.execute = AsyncMock()
    uid = uuid4()

    with patch("app.vision.infrastructure.food_log_writer.check_and_increment_food_log_slot", return_value=0):
        with patch("app.vision.infrastructure.food_log_writer.utc_today", return_value="2026-08-27"):
            await persist_food_logs(
                [_item(kcal=400, protein_g=30)],
                user_id=uid,
                meal_time="lunch",
                prompt_sha="abc",
                session=session,
                servings=1,
            )

    call_kwargs = session.execute.call_args[0][1]
    assert call_kwargs["kc"] == 400
    assert call_kwargs["pg"] == 30


@pytest.mark.asyncio
async def test_persist_food_logs_servings_2_halves_macros() -> None:
    """servings=2: kcal and macros halved before INSERT."""
    from app.vision.infrastructure.food_log_writer import persist_food_logs

    session = AsyncMock()
    session.execute = AsyncMock()
    uid = uuid4()

    with patch("app.vision.infrastructure.food_log_writer.check_and_increment_food_log_slot", return_value=0):
        with patch("app.vision.infrastructure.food_log_writer.utc_today", return_value="2026-08-27"):
            await persist_food_logs(
                [_item(kcal=400, protein_g=30, carbs_g=40, fat_g=10, fiber_g=4, sugar_g=6, amount_g=200.0)],
                user_id=uid,
                meal_time="lunch",
                prompt_sha="abc",
                session=session,
                servings=2,
            )

    kw = session.execute.call_args[0][1]
    assert kw["kc"] == 200      # 400 / 2
    assert kw["pg"] == 15       # 30 / 2
    assert kw["cg"] == 20       # 40 / 2
    assert kw["fg"] == 5        # 10 / 2
    assert kw["fibg"] == 2      # 4 / 2
    assert kw["sug"] == 3       # 6 / 2
    assert math.isclose(kw["ag"], 100.0, abs_tol=0.2)  # 200 / 2


@pytest.mark.asyncio
async def test_persist_food_logs_servings_4() -> None:
    """servings=4: kcal quartered."""
    from app.vision.infrastructure.food_log_writer import persist_food_logs

    session = AsyncMock()
    session.execute = AsyncMock()
    uid = uuid4()

    with patch("app.vision.infrastructure.food_log_writer.check_and_increment_food_log_slot", return_value=0):
        with patch("app.vision.infrastructure.food_log_writer.utc_today", return_value="2026-08-27"):
            await persist_food_logs(
                [_item(kcal=800, protein_g=60, amount_g=400.0)],
                user_id=uid,
                meal_time="dinner",
                prompt_sha="abc",
                session=session,
                servings=4,
            )

    kw = session.execute.call_args[0][1]
    assert kw["kc"] == 200
    assert kw["pg"] == 15


@pytest.mark.asyncio
async def test_persist_food_logs_servings_0_guard() -> None:
    """servings=0 must not divide by zero — treated as 1."""
    from app.vision.infrastructure.food_log_writer import persist_food_logs

    session = AsyncMock()
    session.execute = AsyncMock()
    uid = uuid4()

    with patch("app.vision.infrastructure.food_log_writer.check_and_increment_food_log_slot", return_value=0):
        with patch("app.vision.infrastructure.food_log_writer.utc_today", return_value="2026-08-27"):
            await persist_food_logs(
                [_item(kcal=400, protein_g=30)],
                user_id=uid,
                meal_time="lunch",
                prompt_sha="abc",
                session=session,
                servings=0,
            )

    kw = session.execute.call_args[0][1]
    assert kw["kc"] == 400   # unchanged (servings=0 → treated as 1)
    assert kw["pg"] == 30


# ---------------------------------------------------------------------------
# VisionJob entity — servings field
# ---------------------------------------------------------------------------

def test_vision_job_default_servings_is_1() -> None:
    job = VisionJob()
    assert job.servings == 1


def test_vision_job_stores_servings() -> None:
    job = VisionJob(servings=3)
    assert job.servings == 3


# ---------------------------------------------------------------------------
# SubmitPhoto — clamps servings 1..8
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_photo_clamps_servings_above_8() -> None:
    """servings=10 clamped to 8."""
    repo = AsyncMock()
    repo.save = AsyncMock()
    compressor = AsyncMock()
    compressor.compress = AsyncMock(return_value=MagicMock(bytes_=b"x" * 100, format="jpeg"))
    bus = AsyncMock()
    bus.publish = AsyncMock()
    enqueue_calls: list = []

    async def _enqueue(task_name: str, **kwargs):  # noqa: ANN001
        enqueue_calls.append(kwargs)

    with patch("app.vision.application.submit_photo.assert_mime_matches", return_value="image/jpeg"):
        with patch("app.vision.application.submit_photo.get_settings") as mock_settings:
            mock_settings.return_value.vision_food_prefilter_enabled = False
            uc = SubmitPhoto(repo=repo, compressor=compressor, bus=bus, enqueue=_enqueue)
            await uc(
                user_id=uuid4(),
                meal_time="lunch",
                raw_bytes=b"x" * 100,
                mime="image/jpeg",
                idempotency_key="key1",
                servings=10,
            )

    assert enqueue_calls[0]["servings"] == 8


@pytest.mark.asyncio
async def test_per_serving_kcal_half_of_total_for_2_servings() -> None:
    """per_serving.kcal must be total_kcal / 2 when servings=2.

    Ensures food_log_writer divides correctly and the invariant:
    sum(per_serving macros * servings) ≈ sum(full plate macros).
    """
    from app.vision.infrastructure.food_log_writer import persist_food_logs

    session = AsyncMock()
    session.execute = AsyncMock()
    uid = uuid4()
    items = [
        _item(kcal=600, protein_g=40, carbs_g=60, fat_g=20, fiber_g=6, sugar_g=8, amount_g=300.0),
        _item(kcal=200, protein_g=10, carbs_g=20, fat_g=5, fiber_g=2, sugar_g=2, amount_g=100.0),
    ]

    with patch("app.vision.infrastructure.food_log_writer.check_and_increment_food_log_slot", return_value=0):
        with patch("app.vision.infrastructure.food_log_writer.utc_today", return_value="2026-08-27"):
            await persist_food_logs(
                items,
                user_id=uid,
                meal_time="lunch",
                prompt_sha="abc",
                session=session,
                servings=2,
            )

    calls = session.execute.call_args_list
    assert len(calls) == 2

    kw0 = calls[0][0][1]
    kw1 = calls[1][0][1]

    # Each item halved
    assert kw0["kc"] == 300   # 600 / 2
    assert kw0["pg"] == 20    # 40 / 2
    assert kw1["kc"] == 100   # 200 / 2
    assert kw1["pg"] == 5     # 10 / 2

    # Re-compose: 2 × (300+100) = 800 == original 600+200
    assert kw0["kc"] + kw1["kc"] == (600 + 200) // 2


@pytest.mark.asyncio
async def test_submit_photo_clamps_servings_below_1() -> None:
    """servings=-1 clamped to 1."""
    repo = AsyncMock()
    repo.save = AsyncMock()
    compressor = AsyncMock()
    compressor.compress = AsyncMock(return_value=MagicMock(bytes_=b"x" * 100, format="jpeg"))
    bus = AsyncMock()
    bus.publish = AsyncMock()
    enqueue_calls: list = []

    async def _enqueue(task_name: str, **kwargs):  # noqa: ANN001
        enqueue_calls.append(kwargs)

    with patch("app.vision.application.submit_photo.assert_mime_matches", return_value="image/jpeg"):
        with patch("app.vision.application.submit_photo.get_settings") as mock_settings:
            mock_settings.return_value.vision_food_prefilter_enabled = False
            uc = SubmitPhoto(repo=repo, compressor=compressor, bus=bus, enqueue=_enqueue)
            await uc(
                user_id=uuid4(),
                meal_time="lunch",
                raw_bytes=b"x" * 100,
                mime="image/jpeg",
                idempotency_key="key2",
                servings=-1,
            )

    assert enqueue_calls[0]["servings"] == 1
